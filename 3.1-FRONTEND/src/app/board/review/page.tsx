import { permanentRedirect } from 'next/navigation';

// 旧路径兼容（SPEC-20261111-A §3.1）：308 → dashboard 壳内
export default function LegacyBoardReviewPage() {
  permanentRedirect('/dashboard/board/review');
}
