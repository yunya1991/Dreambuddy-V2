/**
 * UID 生成器 — 格式: U + 10位随机字符
 * 字符集: 56字符 (去除易混淆的 0/O/1/l/I)
 */
const UID_CHARSET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz";

export function generateUID(): string {
  const array = new Uint8Array(10);
  crypto.getRandomValues(array);
  let uid = "U";
  for (let i = 0; i < 10; i++) {
    uid += UID_CHARSET[array[i] % UID_CHARSET.length];
  }
  return uid;
}

/**
 * 订单号生成器 — 格式: CG + YYYYMMDD + 4位序号
 */
let orderCounter = 0;
export function generateOrderNo(): string {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, "");
  const seq = String(++orderCounter).padStart(4, "0");
  return `CG${dateStr}${seq}`;
}

/**
 * 6位验证码生成器
 */
export function generateVerifyCode(): string {
  const array = new Uint8Array(6);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => String(b % 10)).join("");
}
