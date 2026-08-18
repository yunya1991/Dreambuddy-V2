import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '公司架构 - Dream 产物中心',
};

export default function OrgLayout({ children }: { children: React.ReactNode }) {
  return children;
}
