/**
 * AES-256-GCM 加密/解密工具
 * 用于API配置凭证的安全存储
 */
import crypto from 'crypto';

const ALGORITHM = 'aes-256-gcm';
const IV_LENGTH = 16;
const AUTH_TAG_LENGTH = 16;

function getKey(): Buffer {
  const key = process.env.ENCRYPTION_KEY;
  if (!key) {
    throw new Error('ENCRYPTION_KEY environment variable is not set');
  }
  // 确保密钥为32字节(AES-256)
  return crypto.scryptSync(key, 'dream-gateway-salt', 32);
}

/**
 * 加密明文数据
 * @returns { encryptedData, iv, authTag } 均为 hex 编码字符串
 */
export function encrypt(plaintext: string): {
  encryptedData: string;
  iv: string;
  authTag: string;
} {
  const key = getKey();
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv, {
    authTagLength: AUTH_TAG_LENGTH,
  });

  let encrypted = cipher.update(plaintext, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  const authTag = cipher.getAuthTag();

  return {
    encryptedData: encrypted,
    iv: iv.toString('hex'),
    authTag: authTag.toString('hex'),
  };
}

/**
 * 解密数据
 * @param encryptedData hex编码的密文
 * @param iv hex编码的IV
 * @param authTag hex编码的GCM认证标签
 * @returns 解密后的明文
 */
export function decrypt(
  encryptedData: string,
  iv: string,
  authTag: string
): string {
  const key = getKey();
  const ivBuf = Buffer.from(iv, 'hex');
  const authTagBuf = Buffer.from(authTag, 'hex');

  const decipher = crypto.createDecipheriv(ALGORITHM, key, ivBuf, {
    authTagLength: AUTH_TAG_LENGTH,
  });
  decipher.setAuthTag(authTagBuf);

  let decrypted = decipher.update(encryptedData, 'hex', 'utf8');
  decrypted += decipher.final('utf8');

  return decrypted;
}

/**
 * 生成密钥提示 (首2位 + *** + 末2位)
 * 例如: "ab***yz"
 */
export function generateKeyHint(key: string): string {
  if (!key || key.length < 6) return '***';
  return `${key.slice(0, 2)}***${key.slice(-2)}`;
}
