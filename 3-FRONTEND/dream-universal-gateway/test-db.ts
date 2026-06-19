import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcryptjs';

async function main() {
  const p = new PrismaClient();
  const email = '1234@163.com';
  
  const user = await p.user.findUnique({ where: { email } });
  console.log('User:', user);
  
  if (user) {
    const isValid = await bcrypt.compare('123456', user.passwordHash);
    console.log('Password valid:', isValid);
    
    const newHash = await bcrypt.hash('123456', 10);
    console.log('New hash:', newHash);
    console.log('Stored hash:', user.passwordHash);
    console.log('Hashes equal:', newHash === user.passwordHash);
  }
  
  await p.$disconnect();
}

main().catch(console.error);
