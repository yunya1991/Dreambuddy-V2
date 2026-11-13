import { redirect } from 'next/navigation';

// SPEC-52 F1：全站唯一聊天入口 = /dashboard/agent（兼容旧 /chat 链接，直接重定向）
export default function ChatPage() {
  redirect('/dashboard/agent?mode=task');
}
