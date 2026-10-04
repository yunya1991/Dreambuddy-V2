-- P1: 治理面板投票表
-- 创建 proposal_votes 表 + Vote 枚举 (FOR/AGAINST)
-- voter 为字符串 uid, 无外键关联 User 表 (P2 接 next-auth + User 关联)

CREATE TABLE "proposal_votes" (
    "id" TEXT NOT NULL,
    "proposalId" TEXT NOT NULL,
    "voter" TEXT NOT NULL,
    "vote" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "proposal_votes_pkey" PRIMARY KEY ("id")
);

CREATE TYPE "Vote" AS ENUM ('FOR', 'AGAINST');
