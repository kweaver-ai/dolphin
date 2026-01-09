
import asyncio
import threading
import sys
import select
from typing import Optional

async def _monitor_interrupt(token, stop_event: threading.Event):
    """Monitor stdin for ESC key in a separate thread."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _blocking_stdin_monitor, token, stop_event)
    except:
        pass

def _blocking_stdin_monitor(token, stop_event: threading.Event):
    """Blocking monitor for ESC key using select/termios."""
    import tty
    import termios
    
    if not sys.stdin.isatty():
        return
        
    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except:
        return

    try:
        # Set to cbreak mode to read keys without waiting for newline
        tty.setcbreak(fd)
        while not stop_event.is_set():
            # Check if input is available (timeout 0.1s)
            if select.select([sys.stdin], [], [], 0.1)[0]:
                try:
                    key = sys.stdin.read(1)
                    if key == '\x1b': # ESC code
                        token.trigger_interrupt()
                        # Once triggered, we can stop
                        break
                    elif key == '\x03': # Ctrl-C
                        # Also trigger interrupt on Ctrl-C
                        token.trigger_interrupt()
                        break
                    elif key in ('\r', '\n'): # Enter
                        # Treat Enter as an interrupt signal only if there is buffered text
                        # This makes the UI feel like a real-time chat
                        if token._realtime_input_buffer:
                            token.trigger_interrupt()
                            break
                        # Otherwise ignore empty Enter
                    else:
                        # Append to buffer and ECHO to the fixed input line
                        buffer = token.append_realtime_input(key)
                        
                        # Echoing with cursor preservation
                        try:
                            import shutil
                            height = shutil.get_terminal_size().lines
                            # Save cursor, move to bottom line, clear, draw prompt + buffer, restore
                            # We use atomic write to minimize flickering
                            echo_output = (
                                f"\0337"                 # Save cursor
                                f"\033[{height};1H"      # Move to bottom line
                                f"\033[K> {buffer}█"     # Clear and draw with block cursor
                                f"\0338"                 # Restore cursor
                            )
                            sys.stdout.write(echo_output)
                            sys.stdout.flush()
                        except:
                            pass
                except:
                    break
    except:
        pass
    finally:
        # ABSOLUTELY ESSENTIAL: Restore original terminal settings
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except:
            pass
