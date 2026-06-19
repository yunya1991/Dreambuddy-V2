import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcryptjs';

async function main() {
  const p = new PrismaClient();
  const email = '1234@163.com';
  const displayName = '测试用户';
  const password = '123456';

  const hash = await bcrypt.hash(password, 10);
  
  const existing = await p.user.findUnique({ where: { email } });
  if (existing) {
    console.log('用户已存在，更新密码');
    await p.user.update({ where: { email }, data: { passwordHash: hash } });
  } else {
    console.log('创建新用户');
    await p.user.create({
      data: {
        uid: 'U' + Math.random().toString(36).substring(2, 12),
        email,
        displayName,
        passwordHash: hash,
        role: 'FREE',
      },
    });
  }
  console.log(`✓ 用户已创建/更新: ${email} -> ${password}`);
  await p.$disconnect();
}
main().catch(console.error);