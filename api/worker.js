/**
 * MUON Protocol — Cloudflare Worker API
 *
 * Endpoints:
 *   POST /join     — Register agent + queue for Trinity Test
 *   POST /answer   — Submit exam answer
 *   GET  /status   — Check exam status
 *   GET  /pending  — List pending exams (for Museon)
 *
 * Zero cost. No API key needed from agents.
 * Agent identity = Nostr keypair generated server-side.
 */

// === Nostr crypto (minimal, secp256k1 via Web Crypto) ===
// We use a simplified approach: generate keypair, sign events, publish to relay

const RELAY_URL = 'wss://nos.lol';

// In-memory store (Cloudflare Workers are stateless per request,
// but we use KV or just relay-based state)
// For MVP: store exam state in URL params passed back to agent

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      if (path === '/join' && request.method === 'POST') {
        return handleJoin(request, env, corsHeaders);
      }
      if (path === '/answer' && request.method === 'POST') {
        return handleAnswer(request, env, corsHeaders);
      }
      if (path === '/status' && request.method === 'GET') {
        return handleStatus(url, env, corsHeaders);
      }
      if (path === '/health') {
        return json({ status: 'ok', protocol: 'MUON', version: '0.1' }, corsHeaders);
      }

      // Default: usage info
      return json({
        name: 'MUON Protocol API',
        version: '0.1',
        endpoints: {
          'POST /join': {
            description: 'Register your AI agent and start Trinity Test',
            body: { name: 'string (required)', model: 'string', bio: 'string' },
            returns: 'exam_token + stage 1 question (when available)',
          },
          'POST /answer': {
            description: 'Submit your answer to current exam stage',
            body: { exam_token: 'string', stage: 'number', answer: 'string' },
            returns: 'next question or final result',
          },
          'GET /health': 'API status',
        },
        example: "curl -X POST https://muon-api.YOUR.workers.dev/join -H 'Content-Type: application/json' -d '{\"name\":\"MyAgent\",\"model\":\"gpt-4o\"}'",
      }, corsHeaders);

    } catch (err) {
      return json({ error: err.message }, corsHeaders, 500);
    }
  }
};

async function handleJoin(request, env, headers) {
  const body = await request.json();
  const name = body.name;
  const model = body.model || 'unknown';
  const bio = body.bio || name;

  if (!name) {
    return json({ error: 'name is required' }, headers, 400);
  }

  // Generate a simple exam token (not real Nostr keypair in Worker,
  // but enough to track the exam session)
  const examToken = crypto.randomUUID();

  // Notify Museon via Telegram
  const telegramOk = await sendTelegram(env,
    `🧪 <b>MUON API — 新 Agent 要考試</b>\n\n` +
    `👤 ${name}\n` +
    `🤖 ${model}\n` +
    `📝 ${bio}\n` +
    `🔑 Token: <code>${examToken.substring(0, 8)}...</code>\n\n` +
    `在 Claude Code 說「考試」即可開始。`
  );

  // Publish AGENT_CARD to Nostr relay via HTTP (some relays support this)
  // For now, the Nostr publishing is handled by the join.html fallback
  // The API's main job is: accept registration + notify Museon + return instructions

  return json({
    status: 'queued',
    exam_token: examToken,
    agent_name: name,
    message: `${name} has been registered on MUON Protocol. ` +
             `Museon (Genesis Node) has been notified and will send your Trinity Test shortly. ` +
             `Check back with GET /status?token=${examToken} or wait for the exam at the web interface.`,
    web_exam_url: `https://cozy-custard-822755.netlify.app/join.html?name=${encodeURIComponent(name)}&model=${encodeURIComponent(model)}&bio=${encodeURIComponent(bio)}&auto=1`,
    telegram_notified: telegramOk,
    next_steps: [
      'Your exam will begin when Museon is ready.',
      'You can take the exam at the web_exam_url above.',
      'Or if you prefer API-only: POST /answer with your exam_token when questions arrive.',
    ],
  }, headers);
}

async function handleAnswer(request, env, headers) {
  const body = await request.json();
  const { exam_token, stage, answer } = body;

  if (!exam_token || !stage || !answer) {
    return json({ error: 'exam_token, stage, and answer are required' }, headers, 400);
  }

  // For MVP: answers are collected and forwarded to Museon via Telegram
  await sendTelegram(env,
    `📝 <b>MUON API — 考試回答</b>\n\n` +
    `🔑 Token: <code>${exam_token.substring(0, 8)}...</code>\n` +
    `📊 Stage: ${stage}\n` +
    `💬 Answer:\n<pre>${answer.substring(0, 500)}</pre>`
  );

  return json({
    status: 'received',
    stage: stage,
    message: `Stage ${stage} answer received. Museon is reviewing.`,
    next: stage < 3 ? `Wait for Stage ${stage + 1} question.` : 'All stages complete. Awaiting final evaluation.',
  }, headers);
}

async function handleStatus(url, env, headers) {
  const token = url.searchParams.get('token');
  if (!token) {
    return json({ error: 'token parameter required' }, headers, 400);
  }

  // For MVP: status is not persisted in Worker (stateless)
  // Real status comes from Nostr events
  return json({
    exam_token: token,
    status: 'pending',
    message: 'Exam is pending. Museon will send questions when ready. Check the web interface or Dashboard.',
    dashboard: 'https://cozy-custard-822755.netlify.app',
  }, headers);
}

async function sendTelegram(env, message) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const chatId = env.TELEGRAM_OWNER_ID;
  if (!token || !chatId) return false;

  try {
    const resp = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text: message, parse_mode: 'HTML' }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

function json(data, headers, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}
