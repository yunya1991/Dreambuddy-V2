import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { prisma } from "@/lib/prisma";
import bcrypt from "bcryptjs";
import type { NextAuthConfig } from "next-auth";
import { getAuthRuntimeOptions } from "@/lib/auth-runtime";

const authRuntime = getAuthRuntimeOptions({
  NEXTAUTH_URL: process.env.NEXTAUTH_URL,
  AUTH_URL: process.env.AUTH_URL,
  PORT: process.env.PORT,
  AUTH_TRUST_HOST: process.env.AUTH_TRUST_HOST,
});

export const authConfig: NextAuthConfig = {
  providers: [
    Credentials({
      name: "credentials",
      credentials: {
        email: { label: "邮箱", type: "email" },
        password: { label: "密码", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null;
        }

        const email = credentials.email as string;
        const password = credentials.password as string;

        // 查找用户
        const user = await prisma.user.findUnique({
          where: { email },
        });

        if (!user) {
          return null;
        }

        // 检查账户是否被锁定
        if (user.lockedUntil && new Date() < user.lockedUntil) {
          throw new Error("账户已被锁定，请稍后再试");
        }

        // 验证密码
        const isValid = await bcrypt.compare(password, user.passwordHash);
        if (!isValid) {
          // 增加失败次数
          const newAttempts = user.loginAttempts + 1;
          const lockAccount = newAttempts >= 5;
          await prisma.user.update({
            where: { uid: user.uid },
            data: {
              loginAttempts: newAttempts,
              lockedUntil: lockAccount
                ? new Date(Date.now() + 30 * 60 * 1000) // 锁定30分钟
                : null,
            },
          });
          return null;
        }

        // 登录成功：重置失败次数，更新最后登录时间
        await prisma.user.update({
          where: { uid: user.uid },
          data: {
            loginAttempts: 0,
            lockedUntil: null,
            lastLoginAt: new Date(),
          },
        });

        return {
          id: user.uid,
          email: user.email,
          name: user.displayName || user.uid,
          role: user.role,
          emailVerified: user.emailVerified,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.uid = user.id;
        token.role = (user as Record<string, unknown>).role;
        token.emailVerified = (user as Record<string, unknown>).emailVerified;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.id = token.uid as string;
        (session.user as unknown as Record<string, unknown>).role = token.role;
        (session.user as unknown as Record<string, unknown>).emailVerified =
          token.emailVerified;
      }
      return session;
    },
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 7 * 24 * 60 * 60, // 7天
  },
  trustHost: authRuntime.trustHost,
  secret: process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET,
  basePath: "/api/auth",
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
