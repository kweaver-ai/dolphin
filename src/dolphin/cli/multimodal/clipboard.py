"""
Clipboard image reader for multimodal CLI input.

Provides cross-platform clipboard image reading functionality.

Platform Support (Linux-first for commercial deployments):
- Linux X11: Primary target, requires PIL and xclip/xsel
- macOS: Secondary platform, requires pyobjc (AppKit)
- macOS: Secondary platform, requires pyobjc (AppKit)
- Windows: Fallback, requires PIL
"""

import io
import sys
import os
import base64
from typing import Optional

from dolphin.core.common.multimodal import ClipboardEmptyError
from dolphin.core.logging.logger import get_logger

logger = get_logger("clipboard")


class ClipboardImageReader:
    """Cross-platform clipboard image reader.
    
    Platform priority (Linux-first for commercial deployments):
    - Linux X11: Primary target, uses Pillow's ImageGrab
    - Linux Wayland: Quick fail with clear message
    - macOS: Secondary platform, uses AppKit/Cocoa APIs
    - Windows: Fallback, uses Pillow's ImageGrab
        reader = ClipboardImageReader()
        data = reader.read()
        if data:
            url = reader.to_base64_url(data)
    """
    
    def read(self) -> Optional[bytes]:
        """Read image data from clipboard.
        
        Platform detection order (Linux-first for commercial deployments):
        1. Linux (X11) - Primary target for commercial versions
        2. Linux (Wayland) - Quick fail with clear message
        3. macOS - Secondary platform
        4. Windows - Fallback
        
        Returns:
            PNG image data as bytes, or None if no image in clipboard
            
        Note:
            On failure, logs a warning with platform-specific guidance.
        """
        platform = sys.platform
        import os
        
        try:
            # Linux-first: Commercial versions primarily run on Linux
            if platform.startswith("linux"):
                # Quick check for Wayland (not supported)
                if "WAYLAND_DISPLAY" in os.environ:
                    logger.warning(
                        "Clipboard image read not supported on Wayland. "
                        "Please use file upload instead: /image path/to/image.png"
                    )
                    return None
                
                # Try Linux X11 method (Pillow ImageGrab)
                data = self._read_linux()
                if data is not None:
                    return data
            
            # macOS fallback
            elif platform == "darwin":
                data = self._read_macos()
                if data is not None:
                    return data
            
            # Windows fallback
            elif platform == "win32":
                data = self._read_windows()
                if data is not None:
                    return data
            
            # No image found - this is normal, not an error
            return None
            
        except Exception as e:
            # Log platform-specific guidance
            self._log_platform_error(platform, e)
            return None
    
    def _log_platform_error(self, platform: str, error: Exception) -> None:
        """Log platform-specific error message with helpful guidance.
        
        Args:
            platform: sys.platform value
            error: The exception that occurred
        """
        if platform == "darwin":
            logger.warning(
                f"Clipboard image read failed on macOS: {error}. "
                f"Install pyobjc: pip install pyobjc-framework-Cocoa"
            )
        elif platform.startswith("linux"):
            # Detect Wayland
            wayland_display = sys.platform.startswith("linux") and "WAYLAND_DISPLAY" in __import__("os").environ
            if wayland_display:
                logger.warning(
                    f"Clipboard image read not supported on Wayland. "
                    f"Please use file upload instead: /image path/to/image.png"
                )
            else:
                logger.warning(
                    f"Clipboard image read failed on Linux: {error}. "
                    f"Install dependencies: pip install pillow && sudo apt-get install xclip"
                )
        elif platform == "win32":
            logger.warning(
                f"Clipboard image read failed on Windows: {error}. "
                f"Install Pillow: pip install pillow"
            )
        else:
            logger.warning(
                f"Clipboard image read failed on {platform}: {error}"
            )
    
    def _read_macos(self) -> Optional[bytes]:
        """Read clipboard on macOS using AppKit.
        
        Returns:
            Image data as PNG bytes, or None if not available
            
        Raises:
            ImportError: If pyobjc is not installed
        """
        try:
            from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeTIFF
            
            pb = NSPasteboard.generalPasteboard()
            
            # Try PNG first
            data = pb.dataForType_(NSPasteboardTypePNG)
            if data:
                return bytes(data)
            
            # Try TIFF (macOS screenshots are often TIFF)
            data = pb.dataForType_(NSPasteboardTypeTIFF)
            if data:
                return self._convert_to_png(bytes(data))
            
            return None
        except ImportError as e:
            # AppKit not available - re-raise for proper error handling
            raise ImportError(
                "pyobjc not installed. Install with: pip install pyobjc-framework-Cocoa"
            ) from e
    
    def _convert_to_png(self, image_data: bytes) -> bytes:
        """Convert image data to PNG format.
        
        Args:
            image_data: Image data in any format supported by Pillow
            
        Returns:
            PNG image data
        """
        try:
            from PIL import Image
            
            img = Image.open(io.BytesIO(image_data))
            output = io.BytesIO()
            
            # Handle RGBA to RGB conversion if needed
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                # Keep as PNG to preserve transparency
                img.save(output, format='PNG')
            else:
                img.save(output, format='PNG')
            
            return output.getvalue()
        except Exception as e:
            raise RuntimeError(f"Failed to convert image to PNG: {e}")
    
    def _read_linux(self) -> Optional[bytes]:
        """Read clipboard on Linux X11 using Pillow's ImageGrab.
        
        Returns:
            Image data as PNG bytes, or None if not available
            
        Raises:
            ImportError: If PIL is not installed
            RuntimeError: If clipboard access fails (e.g., no X server)
        """
        try:
            from PIL import ImageGrab
            
            img = ImageGrab.grabclipboard()
            if img is None:
                return None
            
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
        except ImportError as e:
            # Pillow not installed - re-raise for proper error handling
            raise ImportError(
                "Pillow not installed. Install with: pip install pillow"
            ) from e
    
    def _read_windows(self) -> Optional[bytes]:
        """Read clipboard on Windows using Pillow's ImageGrab.
        
        Returns:
            Image data as PNG bytes, or None if not available
            
        Raises:
            ImportError: If PIL is not installed
            RuntimeError: If clipboard access fails
        """
        try:
            from PIL import ImageGrab
            
            img = ImageGrab.grabclipboard()
            if img is None:
                return None
            
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
        except ImportError as e:
            # Pillow not installed - re-raise for proper error handling
            raise ImportError(
                "Pillow not installed. Install with: pip install pillow"
            ) from e
    
    def to_base64_url(self, image_data: bytes, mime_type: str = "image/png") -> str:
        """Convert image data to base64 data URL.
        
        Args:
            image_data: Raw image bytes
            mime_type: MIME type of the image (default: image/png)
            
        Returns:
            Data URL string (e.g., "data:image/png;base64,...")
        """
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{b64}"
    
    def read_as_base64_url(self) -> str:
        """Read clipboard image and return as base64 data URL.
        
        Returns:
            Data URL string
            
        Raises:
            ClipboardEmptyError: If no image in clipboard
        """
        data = self.read()
        if data is None:
            raise ClipboardEmptyError("No image found in clipboard")
        return self.to_base64_url(data)
    
    def has_image(self) -> bool:
        """Check if clipboard contains an image.
        
        Returns:
            True if clipboard has an image
        """
        return self.read() is not None
    
    @staticmethod
    def get_platform_support_info() -> dict:
        """Get platform-specific clipboard support information.
        
        Returns:
            Dictionary with platform support details
        """
        platform = sys.platform
        import os
        
        info = {
            "platform": platform,
            "supported": True,
            "requirements": [],
            "notes": []
        }
        
        if platform == "darwin":
            info["requirements"] = ["pyobjc-framework-Cocoa"]
            info["notes"] = ["May require clipboard access permission in System Preferences"]
            try:
                import AppKit
                info["installed"] = True
            except ImportError:
                info["installed"] = False
                
        elif platform.startswith("linux"):
            wayland = "WAYLAND_DISPLAY" in os.environ
            if wayland:
                info["supported"] = False
                info["notes"] = [
                    "Wayland display server detected",
                    "Clipboard image reading not supported",
                    "Use file upload instead: /image path/to/file.png"
                ]
            else:
                info["requirements"] = ["pillow", "xclip or xsel (system package)"]
                info["notes"] = ["Requires X11 display server"]
                try:
                    from PIL import ImageGrab
                    info["installed"] = True
                except ImportError:
                    info["installed"] = False
                    
        elif platform == "win32":
            info["requirements"] = ["pillow"]
            try:
                from PIL import ImageGrab
                info["installed"] = True
            except ImportError:
                info["installed"] = False
        else:
            info["supported"] = False
            info["notes"] = [f"Platform '{platform}' not explicitly supported"]
        
        return info