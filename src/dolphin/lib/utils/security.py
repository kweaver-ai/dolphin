import base64
import os
from typing import Optional
from dolphin.core.logging.logger import get_logger

logger = get_logger()


class SecurityUtils:
    """Security utility class, providing encryption and decryption functions"""

    # Default salt value; in actual applications, it should be obtained from environment variables or configurations.
    DEFAULT_SALT = b"dolphin_default_salt_value"
    
    # 缓存 cryptography 模块（延迟导入）
    _cryptography = None
    
    @classmethod
    def _get_cryptography(cls):
        """获取 cryptography 模块（延迟导入）"""
        if cls._cryptography is None:
            try:
                from cryptography.fernet import Fernet
                from cryptography.hazmat.backends import default_backend
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                cls._cryptography = {
                    'Fernet': Fernet,
                    'default_backend': default_backend,
                    'hashes': hashes,
                    'PBKDF2HMAC': PBKDF2HMAC,
                }
            except ImportError:
                logger.error("cryptography is required for SecurityUtils but not installed. Please install it: pip install cryptography")
                raise ImportError("cryptography is required for SecurityUtils but not installed. Please install it: pip install cryptography")
        return cls._cryptography

    @staticmethod
    def _get_key(password: str, salt: Optional[bytes] = None) -> bytes:
        """Generate encryption key

        Args:
            password: The password used to generate the key
            salt: Optional salt value; if not provided, a default salt value is used

        Returns:
            bytes: The generated key
        """
        crypto = SecurityUtils._get_cryptography()
        PBKDF2HMAC = crypto['PBKDF2HMAC']
        hashes = crypto['hashes']
        default_backend = crypto['default_backend']
        
        if not salt:
            salt = SecurityUtils.DEFAULT_SALT

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    @staticmethod
    def encrypt(text: str, password: str, salt: Optional[bytes] = None) -> str:
        """Encrypted text

        Args:
            text: The text to be encrypted
            password: The password used to generate the key
            salt: Optional salt value

        Returns:
            str: The encrypted text (Base64 encoded)
        """
        try:
            crypto = SecurityUtils._get_cryptography()
            Fernet = crypto['Fernet']
            key = SecurityUtils._get_key(password, salt)
            f = Fernet(key)
            encrypted_data = f.encrypt(text.encode())
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except ImportError:
            raise
        except Exception as e:
            logger.error(f"加密failed: {str(e)}")
            raise RuntimeError(f"加密failed: {str(e)}")

    @staticmethod
    def decrypt(
        encrypted_text: str, password: str, salt: Optional[bytes] = None
    ) -> str:
        """Decrypt text

        Args:
            encrypted_text: The encrypted text (Base64 encoded)
            password: The password used to generate the key
            salt: Optional salt value

        Returns:
            str: The decrypted text
        """
        try:
            crypto = SecurityUtils._get_cryptography()
            Fernet = crypto['Fernet']
            key = SecurityUtils._get_key(password, salt)
            f = Fernet(key)
            # First, perform Base64 decoding on the encrypted text.
            decoded_data = base64.urlsafe_b64decode(encrypted_text.encode())
            decrypted_data = f.decrypt(decoded_data)
            return decrypted_data.decode()
        except ImportError:
            raise
        except Exception as e:
            logger.error(f"解密failed: {str(e)}")
            return encrypted_text  # Return the original encrypted text when decryption fails

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet key

        Returns:
            str: The generated key (Base64-encoded string)
        """
        crypto = SecurityUtils._get_cryptography()
        Fernet = crypto['Fernet']
        key = Fernet.generate_key()
        return key.decode()

    @staticmethod
    def get_env_password() -> str:
        """Get password from environment variables

        Returns:
            str: Password obtained from environment variables, or default value if not set
        """
        return os.environ.get("DOLPHIN_PASSWORD", "default_password_please_change_me")
