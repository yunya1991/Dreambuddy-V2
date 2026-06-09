'use client';

import { useEffect, useRef } from 'react';

/**
 * Pagefind 全文检索组件
 * 
 * 功能:
 * 1. 加载 Pagefind JS 模块
 * 2. 打开 Pagefind 搜索UI
 * 3. 支持自定义触发按钮
 */

interface PagefindSearchProps {
  buttonText?: string;
  className?: string;
}

export default function PagefindSearch({ 
  buttonText = '🔍 全文检索', 
  className = '' 
}: PagefindSearchProps) {
  const pagefindLoaded = useRef(false);

  useEffect(() => {
    // 动态加载 Pagefind (仅在生产环境/静态导出时)
    if (process.env.NODE_ENV === 'production' && !pagefindLoaded.current) {
      const script = document.createElement('script');
      script.src = '/_pagefind/pagefind.js';
      script.async = true;
      
      script.onload = () => {
        pagefindLoaded.current = true;
        console.log('✅ Pagefind 已加载');
      };
      
      script.onerror = () => {
        console.warn('⚠️ Pagefind 加载失败 (可能不在静态导出模式)');
      };
      
      document.head.appendChild(script);
    }
  }, []);

  const openPagefind = async () => {
    try {
      // 检查 Pagefind 是否可用
      if (typeof window !== 'undefined' && (window as any).pagefind) {
        await (window as any).pagefind.search();
      } else {
        alert('⚠️ Pagefind 未加载!\n\n请确保:\n1. 已运行静态导出构建\n2. 在 out/ 目录中运行服务');
      }
    } catch (error) {
      console.error('❌ Pagefind 打开失败:', error);
    }
  };

  // 开发环境提示
  if (process.env.NODE_ENV === 'development') {
    return (
      <button
        onClick={() => alert('🔍 Pagefind 仅在静态导出模式下可用!\n\n使用方法:\n1. NEXT_PUBLIC_STATIC_EXPORT=true npm run build\n2. 打开 out/index.html')}
        className={`px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-md ${className}`}
        title="Pagefind 仅在静态导出模式下可用"
      >
        {buttonText} (静态模式)
      </button>
    );
  }

  return (
    <button
      onClick={openPagefind}
      className={`px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-md shadow-sm ${className}`}
      title="打开全文检索"
    >
      {buttonText}
    </button>
  );
}
