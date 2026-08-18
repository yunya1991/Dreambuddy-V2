/**
 * API配置 CRUD 路由
 * GET  - 获取当前用户的API配置列表（脱敏）
 * POST - 添加新API配置（加密存储）
 * PUT  - 更新API配置
 * DELETE - 删除API配置
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveApiKeysRouteUid } from '@/lib/development-route-uids';
import { encrypt, generateKeyHint } from '@/lib/encryption';

// GET /api/config/api-keys
export async function GET(request: NextRequest) {
  const uid = await resolveApiKeysRouteUid(request);

  try {
    const configs = await prisma.apiConfig.findMany({
      where: { uid },
      select: {
        id: true,
        category: true,
        provider: true,
        label: true,
        keyHint: true,
        environment: true,
        baseUrl: true,
        isVerified: true,
        lastVerifiedAt: true,
        createdAt: true,
        updatedAt: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({ success: true, data: configs });
  } catch (error) {
    console.error('获取API配置失败:', error);
    return NextResponse.json(
      { success: false, error: '获取API配置失败' },
      { status: 500 }
    );
  }
}

// POST /api/config/api-keys
export async function POST(request: NextRequest) {
  const uid = await resolveApiKeysRouteUid(request);

  try {
    const body = await request.json();
    const { category, provider, label, apiKey, secretKey, passphrase, environment, baseUrl } = body;

    // 验证必填字段
    if (!category || !provider || !label || !apiKey || !secretKey) {
      return NextResponse.json(
        { success: false, error: '缺少必填字段: category, provider, label, apiKey, secretKey' },
        { status: 400 }
      );
    }

    // 检查重复标签
    const existing = await prisma.apiConfig.findUnique({
      where: { uid_category_provider_label: { uid, category, provider, label } },
    });
    if (existing) {
      return NextResponse.json(
        { success: false, error: '相同类别+提供商+标签的配置已存在' },
        { status: 409 }
      );
    }

    // 加密凭证
    const credentials = JSON.stringify({ apiKey, secretKey, passphrase: passphrase || '' });
    const { encryptedData, iv, authTag } = encrypt(credentials);
    const keyHint = generateKeyHint(apiKey);

    const config = await prisma.apiConfig.create({
      data: {
        uid,
        category,
        provider,
        label,
        encryptedData,
        iv,
        authTag,
        keyHint,
        environment: environment || 'demo',
        baseUrl: baseUrl || null,
      },
    });

    return NextResponse.json({
      success: true,
      data: {
        id: config.id,
        category: config.category,
        provider: config.provider,
        label: config.label,
        keyHint: config.keyHint,
        environment: config.environment,
        isVerified: config.isVerified,
      },
    });
  } catch (error) {
    console.error('添加API配置失败:', error);
    return NextResponse.json(
      { success: false, error: '添加API配置失败' },
      { status: 500 }
    );
  }
}

// PUT /api/config/api-keys
export async function PUT(request: NextRequest) {
  const uid = await resolveApiKeysRouteUid(request);

  try {
    const body = await request.json();
    const { id, apiKey, secretKey, passphrase, environment, baseUrl, label } = body;

    if (!id) {
      return NextResponse.json(
        { success: false, error: '缺少配置ID' },
        { status: 400 }
      );
    }

    // 验证配置属于当前用户
    const existing = await prisma.apiConfig.findFirst({ where: { id, uid } });
    if (!existing) {
      return NextResponse.json(
        { success: false, error: '配置不存在或无权限' },
        { status: 404 }
      );
    }

    // 如果提供了新凭证，重新加密
    const updateData: Record<string, unknown> = {};
    if (apiKey && secretKey) {
      const credentials = JSON.stringify({
        apiKey,
        secretKey,
        passphrase: passphrase || '',
      });
      const { encryptedData, iv, authTag } = encrypt(credentials);
      updateData.encryptedData = encryptedData;
      updateData.iv = iv;
      updateData.authTag = authTag;
      updateData.keyHint = generateKeyHint(apiKey);
      updateData.isVerified = false; // 凭证变更后需要重新验证
    }
    if (environment) updateData.environment = environment;
    if (baseUrl !== undefined) updateData.baseUrl = baseUrl;
    if (label) updateData.label = label;

    await prisma.apiConfig.update({
      where: { id },
      data: updateData,
    });

    return NextResponse.json({ success: true, data: { id } });
  } catch (error) {
    console.error('更新API配置失败:', error);
    return NextResponse.json(
      { success: false, error: '更新API配置失败' },
      { status: 500 }
    );
  }
}

// DELETE /api/config/api-keys
export async function DELETE(request: NextRequest) {
  const uid = await resolveApiKeysRouteUid(request);

  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get('id');

    if (!id) {
      return NextResponse.json(
        { success: false, error: '缺少配置ID' },
        { status: 400 }
      );
    }

    // 验证配置属于当前用户
    const existing = await prisma.apiConfig.findFirst({ where: { id, uid } });
    if (!existing) {
      return NextResponse.json(
        { success: false, error: '配置不存在或无权限' },
        { status: 404 }
      );
    }

    await prisma.apiConfig.delete({ where: { id } });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('删除API配置失败:', error);
    return NextResponse.json(
      { success: false, error: '删除API配置失败' },
      { status: 500 }
    );
  }
}
