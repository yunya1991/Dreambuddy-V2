/*
  Warnings:

  - Added the required column `label` to the `channel_configs` table without a default value. This is not possible if the table is not empty.

*/
-- CreateEnum
CREATE TYPE "TradeMode" AS ENUM ('SPOT_MODE', 'SWAP_MODE', 'FUTURES_MODE', 'OPTIONS_MODE', 'MARGIN_MODE');

-- CreateEnum
CREATE TYPE "MarginMode" AS ENUM ('CROSS', 'ISOLATED');

-- CreateEnum
CREATE TYPE "PositionMode" AS ENUM ('NET', 'HEDGE');

-- CreateEnum
CREATE TYPE "OptionsType" AS ENUM ('CALL', 'PUT');

-- AlterTable
ALTER TABLE "channel_configs" ADD COLUMN     "label" TEXT NOT NULL;

-- AlterTable
ALTER TABLE "user_profiles" ADD COLUMN     "allowedTradeModes" TEXT[] DEFAULT ARRAY['SPOT_MODE']::TEXT[],
ADD COLUMN     "expiryDate" TEXT,
ADD COLUMN     "marginMode" "MarginMode",
ADD COLUMN     "optionsType" "OptionsType",
ADD COLUMN     "positionMode" "PositionMode" NOT NULL DEFAULT 'NET',
ADD COLUMN     "tradeMode" "TradeMode" NOT NULL DEFAULT 'SPOT_MODE';
