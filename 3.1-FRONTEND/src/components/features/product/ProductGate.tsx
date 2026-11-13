'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryKey, queryStaleTime } from '@/lib/query-keys';
import { product, type ProductEntitlement } from '@/lib/product-client';
import { V3Badge } from '@/components';

// SPEC-52 F2 / §9.5：未开通时页面可见但操作锁定。
// 前端只做体验层锁定；服务端 403 PRODUCT_NOT_ENTITLED 才是最终门禁。

export function useProductEntitlement() {
  const query = useQuery({
    queryKey: queryKey('product', 'entitlement'),
    queryFn: () => product.entitlement(),
    staleTime: queryStaleTime('product'),
    retry: false,
  });

  const entitlement: ProductEntitlement | undefined = query.data;
  // 查询失败/加载中按「可用」渲染（fail-open 体验），服务端仍会 fail-closed 拒绝
  const entitled = entitlement ? entitlement.status === 'active' : true;

  return { entitlement, entitled, loading: query.isLoading };
}

export function ProductLockedNotice({ className = '' }: { className?: string }) {
  return (
    <div
      className={`rounded-lg border border-amber-700/40 bg-amber-900/15 px-3 py-2.5 text-[11px] text-amber-300 ${className}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <V3Badge variant="warning">未开通</V3Badge>
        <span className="font-medium">AI 交易产品包未开通，操作已锁定</span>
      </div>
      <p className="text-amber-400/80 leading-relaxed">
        页面与功能说明可浏览，真实账户数据不加载、下单与凭证写入接口返回 403。
        本地单账户默认开通；如需验证锁定形态，可设置环境变量{' '}
        <span className="font-mono">PRODUCT_AI_TRADING_STATUS=inactive</span>。
      </p>
    </div>
  );
}

export default ProductLockedNotice;
