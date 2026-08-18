import { NextRequest, NextResponse } from 'next/server';
import { loadSessionHistory, clearSessionHistory } from '@/lib/chat-history';
import { getContextForLLM } from '@/lib/context-compression';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const sessionId = searchParams.get('session_id');
    const action = searchParams.get('action');

    if (!sessionId) {
      return NextResponse.json(
        { success: false, error: 'session_id is required' },
        { status: 400 }
      );
    }

    if (action === 'context') {
      const context = await getContextForLLM(sessionId);
      return NextResponse.json({
        success: true,
        data: context,
      });
    }

    const history = loadSessionHistory(sessionId);

    return NextResponse.json({
      success: true,
      data: {
        session_id: history.session_id,
        created_at: history.created_at,
        updated_at: history.updated_at,
        messages: history.messages,
        summary_level: history.summary_level,
        total_tokens: history.total_tokens,
        message_count: history.messages.length,
      },
    });
  } catch (error) {
    console.error('[ChatHistoryAPI] GET error:', error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const sessionId = searchParams.get('session_id');

    if (!sessionId) {
      return NextResponse.json(
        { success: false, error: 'session_id is required' },
        { status: 400 }
      );
    }

    clearSessionHistory(sessionId);

    return NextResponse.json({
      success: true,
      data: { session_id: sessionId, cleared: true },
    });
  } catch (error) {
    console.error('[ChatHistoryAPI] DELETE error:', error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}
