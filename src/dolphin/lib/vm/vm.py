from abc import abstractmethod
import ast
import os
from typing import Any, Dict, Optional, List
import tempfile
import random
import string

from dolphin.core.config.global_config import VMConfig, VMConnectionType
from dolphin.core.utils.cache_kv import CacheKVMgr, GlobalCacheKVCenter
from dolphin.lib.utils.security import SecurityUtils
from dolphin.core.logging.logger import get_logger


logger = get_logger("vm")

PreImport = [
    "datetime",
    "json",
]


class VM:
    """Virtual machine base class, defining the interface for virtual machine operations"""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to virtual machine

        Returns:
            bool: Whether the connection was successful
        """
        pass

    @abstractmethod
    def execBash(self, command: str) -> str:
        """Execute Bash command

        Args:
            command: The Bash command to execute

        Returns:
            str: Result of the command execution
        """
        pass

    def execPython(
        self, code: str, varDict: Optional[Dict[str, Any]] = None, **kwargs
    ) -> str:
        """Execute Python commands. The Python code can be directly generated as a parameter for tool invocation.
                [Attention] The Python code should be directly generated as a parameter for tool invocation, and it is forbidden to generate code blocks like ```python separately!

        Args:
            code: The Python code to execute. The result should be assigned to return_value at the end of the code.
            varDict: Optional dictionary of variables that will be set in the Python environment before executing the code.

        Returns:
            str: The command execution result, usually the value of return_value or the output/error during execution.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the virtual machine"""
        pass

    @staticmethod
    def deserializePythonResult(result: str) -> Any:
        if not result:
            return result

        if result[0] == "[" or result[0] == "{":
            return ast.literal_eval(result)
        else:
            return result


class VMSSH(VM):
    """SSH-based virtual machine connection implementation"""

    def __init__(self, config: VMConfig, cache_vm: CacheKVMgr):
        """Initialize SSH connection

        Args:
            config: Configuration object containing SSH connection information
        """
        self.config = config
        self.cache_vm = cache_vm
        self.client = None
        self.connected = False
        self.attempt_count = 0
        self._paramiko = None  # 延迟导入 paramiko
    
    def _get_paramiko(self):
        """获取 paramiko 模块（延迟导入）"""
        if self._paramiko is None:
            try:
                import paramiko
                self._paramiko = paramiko
            except ImportError:
                logger.error("paramiko is required for VMSSH but not installed. Please install it: pip install paramiko")
                raise ImportError("paramiko is required for VMSSH but not installed. Please install it: pip install paramiko")
        return self._paramiko

    def connect(self) -> bool:
        """Establish SSH connection using Paramiko

                Supports password authentication and SSH key authentication

        Returns:
            bool: whether the connection is successful
        """
        try:
            paramiko = self._get_paramiko()
        except ImportError:
            return False
        
        if not self.config.validate():
            logger.error("VM配置验证failed")
            return False

        # Reset connection attempt count
        self.attempt_count = 0
        return self._attempt_connect(paramiko)

    def _attempt_connect(self, paramiko) -> bool:
        """Try to connect, with retry support

        Args:
            paramiko: The paramiko module (passed to avoid repeated imports)

        Returns:
            bool: Whether the connection was successful
        """
        
        while self.attempt_count < self.config.retryCount:
            try:
                self.attempt_count += 1
                logger.info(
                    f"正在connect to到 {self.config.host}:{self.config.port} (尝试 {self.attempt_count}/{self.config.retryCount})"
                )

                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                connect_args = {
                    "hostname": self.config.host,
                    "port": self.config.port,
                    "username": self.config.username,
                    "timeout": self.config.timeout,
                }

                # Use SSH key authenticationPrioritize usingSSH密钥认证
                if self.config.sshKeyPath and os.path.exists(self.config.sshKeyPath):
                    logger.info(f"使用SSH密钥认证: {self.config.sshKeyPath}")
                    connect_args["key_filename"] = self.config.sshKeyPath
                else:
                    # Use password authentication
                    logger.info("使用密码认证")
                    password = self._decryptPassword(self.config.encryptedPassword)
                    connect_args["password"] = password

                self.client.connect(**connect_args)
                self.connected = True
                logger.info(f"Successfully connected to {self.config.host}")
                return True

            except Exception as e:
                logger.warning(
                    f"connect tofailed (尝试 {self.attempt_count}/{self.config.retryCount}): {str(e)}"
                )
                if self.client:
                    self.client.close()
                    self.client = None

                # If the maximum number of retries has been reached, return failure
                if self.attempt_count >= self.config.retryCount:
                    logger.error(
                        f"connect tofailed，已达到最大重试次数 ({self.config.retryCount})"
                    )
                    self.connected = False
                    return False

                # Retry after a while
                import time

                time.sleep(2)  # Wait 2 seconds before retrying

        return False

    def _decryptPassword(self, encryptedPassword: str) -> str:
        """Decrypt stored encrypted password

        Args:
            encryptedPassword: Encrypted password

        Returns:
            str: Decrypted password
        """
        try:
            # Get the key for decrypting passwords from environment variables
            password = SecurityUtils.get_env_password()
            # Decrypt saved encrypted passwords
            return SecurityUtils.decrypt(encryptedPassword, password)
        except Exception as e:
            logger.error(f"密码解密failed: {str(e)}")
            # If decryption fails, it may be because the password was not encrypted; return directly.
            return encryptedPassword

    def _checkConnection(self) -> bool:
        """Check the connection status and attempt to connect if not connected.

        Returns:
            bool: Whether the connection is available
        """
        if not self.connected or self.client is None:
            return self.connect()

        # Test whether the connection is still alive
        try:
            transport = self.client.get_transport()
            if transport is None or not transport.is_active():
                logger.warning("SSHconnect to已断开，尝试重新connect to")
                self.disconnect()
                return self.connect()
            return True
        except Exception as e:
            logger.warning(f"检查connect to状态时出错: {str(e)}")
            self.disconnect()
            return self.connect()

    def execBash(self, command: str) -> str:
        """Execute Bash commands via SSH

        Args:
            command: The Bash command to execute

        Returns:
            str: The result of the command execution
        """
        if not self._checkConnection():
            return "connect tofailed，无法执行命令"

        command = self._preprocessCode(command, "bash")
        try:
            stdin, stdout, stderr = self.client.exec_command(
                f"source base/bin/activate && {command}"
            )

            # Read command output
            output = stdout.read().decode("utf-8")
            error = stderr.read().decode("utf-8")

            if error:
                logger.warning(f"命令执行产生错误: {error}")
                return f"输出: {output}\n错误: {error}"

            return output
        except Exception as e:
            logger.error(f"执行命令时出错: {str(e)}")
            return f"执行命令时出错: {str(e)}"

    def execPython(
        self, code: str, varDict: Optional[Dict[str, Any]] = None, **kwargs
    ) -> str:
        """Execute Python code via SSH, supporting session state persistence.

                To obtain the execution result, assign the value to be returned at the end of the provided code
                to the special variable return_value.
                For example: code="a=1\nb=2\nreturn_value = a+b"

        Args:
            code: The Python code to execute. The last line of the code should assign the result to return_value.
            varDict: Optional dictionary of variables to set in the Python environment before executing the code.
            session_id: Optional session ID to maintain execution state.
            session_manager: Optional session manager instance.

        Returns:
            str: Command execution result, typically the value of return_value or output/errors during execution.
        """
        # Check whether session management is used
        session_id = kwargs.get("session_id")
        session_manager = kwargs.get("session_manager")

        if session_id and session_manager:
            # Handling code with session manager

            session = session_manager.get_or_create_session(session_id)
            code = session_manager.prepare_session_code(code, session, varDict)
            # No longer need to handle varDict separately, already handled in prepare_session_code
            varDict = None
        else:
            # Original Code Processing
            code = self._preprocessCode(code, "python")

        # Generate random suffixes to avoid conflicts
        random_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        remoteTmpFile = f"/tmp/milkie_python_cmd_{os.getpid()}_{random_suffix}.py"
        remoteTmpVarFile = None
        result = "执行failed"  # Default Result
        localTmpFilePath = None
        varDictTmpFilePath = None
        try:
            # Prepare list of Python script lines
            script_lines = []
            # Add necessary imports
            script_lines.append("# -*- coding: utf-8 -*-")
            script_lines.append("import json")
            script_lines.append("import reprlib")
            script_lines.append("return_value = None")

            # Auto-configure matplotlib for Chinese font support
            script_lines.append("")
            script_lines.append("# 自动配置matplotlib中文字体支持")
            script_lines.append("try:")
            script_lines.append("    import matplotlib")
            script_lines.append("    import matplotlib.pyplot as plt")
            script_lines.append("    # 配置matplotlib使用中文字体")
            script_lines.append(
                "    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'DejaVu Sans']"
            )
            script_lines.append(
                "    plt.rcParams['axes.unicode_minus'] = False  # 修复负号显示"
            )
            script_lines.append("    # 重建字体缓存以确保新字体生效")
            script_lines.append("    matplotlib.font_manager.fontManager.__init__()")
            script_lines.append("except ImportError:")
            script_lines.append("    pass  # matplotlib未安装时忽略字体配置")
            script_lines.append("")

            for preImport in PreImport:
                # Avoid duplicate imports
                if f"import {preImport}" not in script_lines:
                    script_lines.append(f"import {preImport}")

            # Add user code
            script_lines.append(code)

            # Concatenate all lines into a script string
            script_content = "\n".join(script_lines)

            # Create a local temporary file to store the script
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as localTmpFile:
                localTmpFile.write(script_content)
                localTmpFilePath = localTmpFile.name

            logger.info(f"本地临时脚本: {localTmpFilePath}")
            logger.info(f"远程临时脚本: {remoteTmpFile}")

            # If a variable dictionary is provided, save it to a temporary JSON file and upload it
            if varDict and isinstance(varDict, dict):
                import json

                # Temporary file for variable dictionary
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                ) as varDictTmpFile:
                    json.dump(varDict, varDictTmpFile, ensure_ascii=False)
                    varDictTmpFilePath = varDictTmpFile.name

                # Upload variable dictionary file to remote server
                remoteTmpVarFile = (
                    f"/tmp/milkie_vars_{os.getpid()}_{random_suffix}.json"
                )
                logger.info(
                    f"将变量字典保存到临时文件并上传: {varDictTmpFilePath} -> {remoteTmpVarFile}"
                )

                if not self.uploadFile(varDictTmpFilePath, remoteTmpVarFile):
                    logger.error("上传变量字典文件failed")
                    raise IOError("上传变量字典文件failed")

                # Modify the script to read a variable dictionary from a file
                prepend_script = [
                    "# 从临时文件读取变量字典",
                    "import json",
                    f"with open('{remoteTmpVarFile}', 'r', encoding='utf-8') as var_file:",
                    "    _var_dict = json.load(var_file)",
                    "globals().update(_var_dict)",
                ]

                # Insert code to read variables at the beginning of the script
                script_content = "\n".join(prepend_script) + "\n" + script_content

                # Rewrite the updated script
                with open(localTmpFilePath, "w", encoding="utf-8") as f:
                    f.write(script_content)

                result = self.cache_vm.getValue("python", [{"content": script_content}])
                if result:
                    return result

            # Upload script files to remote server
            if not self.uploadFile(localTmpFilePath, remoteTmpFile):
                logger.error("上传脚本文件failed")
                raise IOError("上传脚本文件failed")

            # Execute remote script
            execution_output = self.execBash(f"python3 {remoteTmpFile}")
            result = execution_output.strip()
            self.cache_vm.setValue("python", [{"content": script_content}], result)

        except Exception as e:
            logger.error(f"执行Python脚本过程中出错: {str(e)}")
            result = f"执行Python脚本过程中出错: {str(e)}"
        finally:
            # Clean up temporary files
            # self._cleanupTempFile(localTmpFilePath, "local temporary script")
            # self._cleanupTempFile(varDictTmpFilePath, "temporary file for local variable dictionary")

            # Clean remote files
            # if remoteTmpFile:
            # self._cleanupRemoteTempFile(remoteTmpFile, "remote temporary script")

            # if remoteTmpVarFile:
            # self._cleanupRemoteTempFile(remoteTmpVarFile, "remote variable dictionary temporary file")
            pass

        return result

    def uploadFile(self, localPath: str, remotePath: str) -> bool:
        """Upload file to remote server

        Args:
            localPath: local file path
            remotePath: remote file path

        Returns:
            bool: whether the upload was successful
        """
        if not self._checkConnection():
            return False

        try:
            sftp = self.client.open_sftp()

            # Ensure the target directory exists
            remoteDir = os.path.dirname(remotePath)
            if remoteDir:
                try:
                    self.execBash(f"mkdir -p {remoteDir}")
                except Exception as e:
                    logger.warning(f"创建目录failed: {remoteDir}: {str(e)}")

            sftp.put(localPath, remotePath)
            sftp.close()
            logger.info(f"文件上传successful: {localPath} -> {remotePath}")
            return True
        except Exception as e:
            logger.error(f"文件上传failed: {str(e)}")
            return False

    def downloadFile(self, remotePath: str, localPath: str) -> bool:
        """Download a file from a remote server.

        Args:
            remotePath: Remote file path
            localPath: Local file path

        Returns:
            bool: Whether the download was successful
        """
        if not self._checkConnection():
            return False

        try:
            sftp = self.client.open_sftp()

            # Ensure the local target directory exists
            localDir = os.path.dirname(localPath)
            if localDir:
                os.makedirs(localDir, exist_ok=True)

            sftp.get(remotePath, localPath)
            sftp.close()
            logger.info(f"文件下载successful: {remotePath} -> {localPath}")
            return True
        except Exception as e:
            logger.error(f"文件下载failed: {str(e)}")
            return False

    def listDir(self, remotePath: str) -> List[str]:
        """List files and directories in the remote directory

        Args:
            remotePath: Remote directory path

        Returns:
            List[str]: List of files and directories
        """
        if not self._checkConnection():
            return []

        try:
            sftp = self.client.open_sftp()
            files = sftp.listdir(remotePath)
            sftp.close()
            return files
        except Exception as e:
            logger.error(f"列出目录failed: {str(e)}")
            return []

    def disconnect(self) -> None:
        """Disconnect SSH connection"""
        if self.client:
            self.client.close()
            self.client = None
            self.connected = False
            logger.info(f"已断开与 {self.config.host} 的connect to")

    def _preprocessCode(self, code: str, type: str) -> str:
        """Preprocessing code

        Args:
            code: The code to preprocess
        """
        startFlag = f"```{type}"
        endFlag = "```"
        idxStart = code.find(startFlag)
        if idxStart == -1:
            return code

        idxEnd = code.find(endFlag, idxStart + len(startFlag))
        if idxEnd == -1:
            return code[idxStart + len(startFlag) :]
        return code[idxStart + len(startFlag) : idxEnd]

    def _cleanupTempFile(self, filepath: Optional[str], description: str) -> None:
        """Clean up local temporary files

        Args:
            filepath: File path
            description: File description, used for logging
        """
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"已删除{description}: {filepath}")
            except OSError as e:
                logger.warning(f"删除{description}failed: {filepath}, Error: {e}")

    def _cleanupRemoteTempFile(self, remotepath: str, description: str) -> None:
        """Clean up remote temporary files

        Args:
            remotepath: Remote file path
            description: File description, used for logging
        """
        cleanup_result = self.execBash(f"rm -f {remotepath}")
        if any(
            err in cleanup_result for err in ["错误", "Error", "No such file", "failed"]
        ):
            logger.warning(
                f"清理{description}可能failed: {remotepath}, 清理命令输出: {cleanup_result}"
            )
        else:
            logger.info(f"已尝试清理{description}: {remotepath}")

    def __enter__(self):
        """Support context management with the 'with' statement"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the connection when exiting the context"""
        self.disconnect()


class VMFactory:
    """Virtual machine factory class, used to create VM instances of different types"""

    cache_vm = GlobalCacheKVCenter.getCacheMgr("data/cache", category="vm")

    @staticmethod
    def createVM(config: VMConfig) -> VM:
        """Create the corresponding VM instance according to the configuration.

        Args:
            config: VM configuration information

        Returns:
            VM: The created VM instance
        """
        if config.connection_type == VMConnectionType.SSH:
            return VMSSH(config, VMFactory.cache_vm)
        elif config.connection_type == VMConnectionType.DOCKER:
            # Here you can implement VMs of Docker type
            raise NotImplementedError("Docker类型的VM尚未实现")
        else:
            raise ValueError(f"不支持的VMconnect to类型: {config.connectionType}")


if __name__ == "__main__":
    encryptedPassword = SecurityUtils.encrypt(
        "password", SecurityUtils.get_env_password()
    )
    print(encryptedPassword)
    vmConfig = VMConfig(
        host="localhost",
        port=2222,
        username="myuser",
        encryptedPassword=encryptedPassword,
        connectionType=VMConnectionType.SSH,
    )
    vm = VMFactory.createVM(vmConfig)
    print(vm.execPython("import random; print(random.randint(1, 10))"))
