'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import type { LLMConfig } from '@/lib/types';

interface DreamAgentChatProps {
  isOpen: boolean;
  onClose: () => void;
}

type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'error';

interface DreamAgentRealtimeItem {
  id: string;
  summary: string;
  status?: string;
  requestId?: string;
}

export default function DreamAgentChat({ isOpen, onClose }: DreamAgentChatProps) {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant', content: string }>>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [llmConfig, setLLMConfig] = useState<LLMConfig>({
    provider: 'openai',
    model: 'gpt-4',
    apiKey: '',
    apiBase: ''
  });
  const [showSettings, setShowSettings] = useState(false);
  const [isClient, setIsClient] = useState(false);
  const [realtimeStatus, setRealtimeStatus] = useState<RealtimeStatus>('idle');
  const [eventFeed, setEventFeed] = useState<DreamAgentRealtimeItem[]>([]);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const seenRealtimeEventIdsRef = useRef<Set<string>>(new Set());
  
  // Initialize on mount
  useEffect(() => {
    setIsClient(true);
    
    // Load LLM config from localStorage
    try {
      const saved = localStorage.getItem('dream_agent_llm_config');
      if (saved) {
        setLLMConfig(JSON.parse(saved));
      }
    } catch (e) {
      console.error('Failed to load LLM config:', e);
    }
  }, []);
  
  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);
  
  // Save LLM config
  const saveLLMConfig = useCallback((config: LLMConfig) => {
    setLLMConfig(config);
    if (isClient) {
      localStorage.setItem('dream_agent_llm_config', JSON.stringify(config));
    }
  }, [isClient]);

  useEffect(() => {
    if (!isOpen) {
      setRealtimeStatus('idle');
      return;
    }

    setRealtimeStatus('connecting');
    setEventFeed([]);
    seenRealtimeEventIdsRef.current = new Set();

    const es = new EventSource('/api/realtime/stream?channel=dream-agent');
    const pushRealtimeEvent = (payload: DreamAgentRealtimeItem) => {
      if (seenRealtimeEventIdsRef.current.has(payload.id)) {
        return;
      }
      seenRealtimeEventIdsRef.current.add(payload.id);
      setEventFeed((prev) => [...prev.slice(-9), payload]);
    };
    const handleRealtimeData = (data: string) => {
      if (!data) return;
      try {
        const payload = JSON.parse(data) as DreamAgentRealtimeItem;
        pushRealtimeEvent(payload);
      } catch {}
    };
    const handleRealtimeEvent = (event: MessageEvent<string>) => {
      handleRealtimeData(event.data);
    };
    es.onmessage = (event) => {
      handleRealtimeData(event.data);
    };

    es.onopen = () => setRealtimeStatus('open');
    es.addEventListener('realtime', handleRealtimeEvent as EventListener);
    es.onerror = () => {
      setRealtimeStatus('error');
      es.close();
    };

    return () => {
      es.removeEventListener('realtime', handleRealtimeEvent as EventListener);
      es.close();
    };
  }, [isOpen]);
  
  // Call Dream Agent API
  const callDreamAgent = useCallback(async (userInput: string) => {
    setIsLoading(true);
    
    // Add user message
    const userMessage = { role: 'user' as const, content: userInput };
    setMessages(prev => [...prev, userMessage]);
    
    try {
      // Call Dream Agent API
      const response = await fetch('/api/dream-agent/invoke', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          user_input: userInput,
          llm_config: llmConfig  // Send LLM config to backend
        }),
      });
      
      if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`);
      }
      
      const data = await response.json();
      
      if (data.success) {
        // Add assistant message
        const assistantMessage = {
          role: 'assistant' as const,
          content: data.response
        };
        setMessages(prev => [...prev, assistantMessage]);
      } else {
        throw new Error(data.error || 'Unknown error');
      }
      
    } catch (error) {
      console.error('Dream Agent API error:', error);
      
      // Add error message
      const errorMessage = {
        role: 'assistant' as const,
        content: `❌ 错误: ${error instanceof Error ? error.message : '调用 Dream Agent 失败'}\n\n请检查：\n1. 老中台站内 API 是否可用\n2. Dream Agent 后端是否可从中台访问\n3. LLM API Key 是否正确`
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  }, [llmConfig]);
  
  // Handle form submit
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!input.trim() || isLoading) return;
    
    const userInput = input.trim();
    setInput('');
    callDreamAgent(userInput);
  };
  
  if (!isOpen) return null;
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🧠</span>
            <h2 className="text-xl font-bold">Dream Agent</h2>
            <span className="text-sm text-gray-500">- 11 步思维链路</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${
                realtimeStatus === 'open'
                  ? 'bg-green-50 text-green-700'
                  : realtimeStatus === 'connecting'
                    ? 'bg-amber-50 text-amber-700'
                    : realtimeStatus === 'error'
                      ? 'bg-red-50 text-red-700'
                      : 'bg-gray-100 text-gray-500'
              }`}
            >
              {realtimeStatus === 'open'
                ? '实时已连接'
                : realtimeStatus === 'connecting'
                  ? '实时连接中'
                  : realtimeStatus === 'error'
                    ? '实时断开'
                    : '实时未启动'}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            {/* Settings button */}
            <button
              onClick={() => setShowSettings(true)}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition"
              title="设置 LLM API"
            >
              ⚙️
            </button>
            
            {/* Close button */}
            <button
              onClick={onClose}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition"
            >
              ✕
            </button>
          </div>
        </div>
        
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {eventFeed.length > 0 && (
            <div className="mb-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="mb-2 text-xs font-medium text-gray-500">实时状态流</div>
              <div className="space-y-1">
                {eventFeed.map((event) => (
                  <div key={event.id} className="text-xs text-gray-600">
                    {event.summary}
                  </div>
                ))}
              </div>
            </div>
          )}
          {messages.length === 0 ? (
            <div className="text-center text-gray-400 mt-20">
              <div className="text-6xl mb-4">🧠</div>
              <p className="text-lg">开始与 Dream Agent 对话</p>
              <p className="text-sm mt-2">Dream Agent 将执行 11 步思维链路：</p>
              <ol className="text-sm mt-2 text-left inline-block">
                <li>1️⃣ 意图识别</li>
                <li>2️⃣ 调研分析</li>
                <li>3️⃣ 理论知识</li>
                <li>4️⃣ 假设生成</li>
                <li>5️⃣ 测试与观测</li>
                <li>6️⃣ 结论推导</li>
                <li>7️⃣ 落地执行</li>
                <li>8️⃣ 监控</li>
                <li>9️⃣ 复盘</li>
                <li>🔟 做梦</li>
                <li>1️⃣1️⃣ 更新优化</li>
              </ol>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] rounded-lg p-3 ${
                    msg.role === 'user'
                      ? 'bg-blue-500 text-white'
                      : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  <div className="text-xs opacity-70 mb-1">
                    {msg.role === 'user' ? '你' : '🧠 Dream Agent'}
                  </div>
                  <pre className="whitespace-pre-wrap font-sans text-sm">
                    {msg.content}
                  </pre>
                </div>
              </div>
            ))
          )}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-lg p-3">
                <div className="flex items-center gap-2">
                  <div className="animate-spin">⏳</div>
                  <span className="text-sm text-gray-600">Dream Agent 思考中...</span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        
        {/* Input */}
        <form onSubmit={handleSubmit} className="p-4 border-t">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入你的问题..."
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              发送
            </button>
          </div>
        </form>
      </div>
      
      {/* Settings Modal */}
      {showSettings && (
        <SettingsModal
          config={llmConfig}
          onSave={saveLLMConfig}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}

// ===== Settings Modal =====

interface SettingsModalProps {
  config: LLMConfig;
  onSave: (config: LLMConfig) => void;
  onClose: () => void;
}

function SettingsModal({ config, onSave, onClose }: SettingsModalProps) {
  const [provider, setProvider] = useState(config.provider);
  const [model, setModel] = useState(config.model);
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [apiBase, setApiBase] = useState(config.apiBase);
  
  const handleSave = () => {
    onSave({
      provider,
      model,
      apiKey,
      apiBase
    });
    onClose();
  };
  
  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-4">⚙️ LLM API 设置</h3>
        
        <div className="space-y-4">
          {/* Provider */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              LLM 提供商
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as "openai" | "anthropic" | "aliyun")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="openai">OpenAI (GPT)</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="aliyun">阿里云百炼 (通义千问)</option>
            </select>
          </div>
          
          {/* Model */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              模型
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={
                provider === 'openai' ? 'gpt-4' :
                provider === 'anthropic' ? 'claude-3-opus-20240229' :
                'qwen-plus'
              }
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              {provider === 'openai' && '推荐: gpt-4, gpt-3.5-turbo'}
              {provider === 'anthropic' && '推荐: claude-3-opus, claude-3-sonnet'}
              {provider === 'aliyun' && '推荐: qwen-plus, qwen-turbo'}
            </p>
          </div>
          
          {/* API Key */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-xxx"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          
          {/* API Base (Optional) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Base (可选)
            </label>
            <input
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder={
                provider === 'aliyun' ? 'https://dashscope.aliyuncs.com/compatible-mode/v1' : ''
              }
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        
        {/* Buttons */}
        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
