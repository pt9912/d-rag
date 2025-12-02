import express from 'express';
import fetch from 'node-fetch';
import morgan from 'morgan';
import { responses } from './responses.js';

const app = express();
const metricsApp = express();
app.use(express.json());
app.use(morgan('dev'));

const parseNumber = (value, fallback) => {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const normalizeQuestion = (text) => text.trim().replace(/\s+/g, ' ');

const PORT = process.env.PORT || 3978;
const METRICS_PORT = parseNumber(process.env.METRICS_PORT, 9100);
const METRICS_PATH = process.env.METRICS_PATH || '/metrics';
const NLU_ENDPOINT = process.env.NLU_ENDPOINT || 'http://rasa:5005';
const RAG_ENDPOINT = process.env.RAG_ENDPOINT || 'http://rag-service:8000';
const NLU_CONFIDENCE_THRESHOLD = parseNumber(process.env.NLU_CONFIDENCE_THRESHOLD, 0.7);
const NLU_TIMEOUT_MS = parseNumber(process.env.NLU_TIMEOUT_MS, 5000);
const NLU_STATUS_TIMEOUT_MS = parseNumber(process.env.NLU_STATUS_TIMEOUT_MS, 2000);
const NLU_CACHE_SIZE = parseNumber(process.env.NLU_CACHE_SIZE, 500);
const NLU_CACHE_TTL_MS = parseNumber(process.env.NLU_CACHE_TTL_MS, 5 * 60 * 1000);
const CONFIDENCE_BUCKETS = [0, 0.2, 0.4, 0.6, 0.8, 1];

const STATIC_INTENTS = new Set(Object.keys(responses));
const FORWARDABLE_ENTITIES = new Set(['topic', 'doc_type']);

const nluCache = new Map();
const intentCounts = new Map();
const confidenceBucketCounts = Array(CONFIDENCE_BUCKETS.length + 1).fill(0);
let fallbackCount = 0;
let confidenceSum = 0;
let confidenceCount = 0;

const parseRoles = (value) => {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  return [];
};

const mapEntitiesToPayload = (entities = []) => {
  const mapped = {};
  for (const entity of entities) {
    if (!entity || !FORWARDABLE_ENTITIES.has(entity.entity)) continue;
    const value = typeof entity.value === 'string' ? entity.value.trim() : entity.value;
    if (!value || mapped[entity.entity]) continue;
    mapped[entity.entity] = value;
  }
  return mapped;
};

const buildRagPayload = (question, roles, entityPayload) => {
  const payload = { question };
  if (roles.length) {
    payload.roles = roles;
  }
  if (entityPayload && Object.keys(entityPayload).length) {
    return { ...payload, ...entityPayload };
  }
  return payload;
};

const evictOldestCacheEntry = () => {
  const oldestKey = nluCache.keys().next().value;
  if (oldestKey !== undefined) {
    nluCache.delete(oldestKey);
  }
};

const getCachedNlu = (key) => {
  const entry = nluCache.get(key);
  if (!entry) return null;
  if (entry.expiresAt < Date.now()) {
    nluCache.delete(key);
    return null;
  }
  // refresh recency for LRU behavior
  nluCache.delete(key);
  nluCache.set(key, entry);
  return entry.data;
};

const setCachedNlu = (key, data) => {
  nluCache.set(key, { data, expiresAt: Date.now() + NLU_CACHE_TTL_MS });
  if (nluCache.size > NLU_CACHE_SIZE) {
    evictOldestCacheEntry();
  }
};

const requestWithTimeout = async (url, options, timeoutMs) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`Timeout nach ${timeoutMs}ms fuer ${url}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
};

const callNlu = async (text) => {
  const cached = getCachedNlu(text);
  if (cached) {
    console.log('[nlu-cache] hit');
    return cached;
  }

  const response = await requestWithTimeout(
    `${NLU_ENDPOINT}/model/parse`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    },
    NLU_TIMEOUT_MS
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`NLU Anfrage fehlgeschlagen (${response.status}): ${detail}`);
  }

  const result = await response.json();
  setCachedNlu(text, result);
  return result;
};

const callRag = async (payload) => {
  const response = await fetch(`${RAG_ENDPOINT}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`RAG Anfrage fehlgeschlagen (${response.status}): ${detail}`);
  }

  return response.json();
};

const respondWithRag = async (res, payload) => {
  try {
    const data = await callRag(payload);
    return res.json({ answer: data.answer, contexts: data.contexts });
  } catch (error) {
    return res.status(502).json({ error: 'RAG Anfrage fehlgeschlagen', detail: error.message });
  }
};

const logIntent = (intentName, confidence) => {
  const formattedConfidence = Number.isFinite(confidence) ? confidence.toFixed(3) : 'n/a';
  console.log(`[nlu] intent=${intentName || 'unknown'} confidence=${formattedConfidence}`);
};

const recordIntentMetrics = (intentName, confidence, isFallback) => {
  if (intentName) {
    intentCounts.set(intentName, (intentCounts.get(intentName) || 0) + 1);
  }

  if (isFallback) {
    fallbackCount += 1;
  }

  if (Number.isFinite(confidence)) {
    confidenceSum += confidence;
    confidenceCount += 1;
    let bucketIndex = CONFIDENCE_BUCKETS.findIndex((bound) => confidence <= bound);
    if (bucketIndex === -1) {
      bucketIndex = CONFIDENCE_BUCKETS.length;
    }
    confidenceBucketCounts[bucketIndex] += 1;
  }
};

const escapeLabelValue = (value) => value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');

const renderMetrics = () => {
  const lines = [];
  lines.push('# HELP nlu_intent_total Gesamtzahl erkannter Intents');
  lines.push('# TYPE nlu_intent_total counter');
  if (intentCounts.size === 0) {
    lines.push('nlu_intent_total{intent="unknown"} 0');
  } else {
    for (const [intent, count] of intentCounts.entries()) {
      lines.push(`nlu_intent_total{intent="${escapeLabelValue(intent)}"} ${count}`);
    }
  }

  lines.push('# HELP nlu_fallback_total Anzahl Fallback-Routings');
  lines.push('# TYPE nlu_fallback_total counter');
  lines.push(`nlu_fallback_total ${fallbackCount}`);

  lines.push('# HELP nlu_confidence Confidence-Histogramm');
  lines.push('# TYPE nlu_confidence histogram');
  let cumulative = 0;
  CONFIDENCE_BUCKETS.forEach((bound, idx) => {
    cumulative += confidenceBucketCounts[idx];
    lines.push(`nlu_confidence_bucket{le="${bound}"} ${cumulative}`);
  });
  cumulative += confidenceBucketCounts[confidenceBucketCounts.length - 1];
  lines.push('nlu_confidence_bucket{le="+Inf"} ' + cumulative);
  lines.push(`nlu_confidence_sum ${confidenceSum}`);
  lines.push(`nlu_confidence_count ${confidenceCount}`);
  return lines.join('\n') + '\n';
};

const checkNluStatus = async () => {
  const response = await requestWithTimeout(
    `${NLU_ENDPOINT}/status`,
    { method: 'GET', headers: { Accept: 'application/json' } },
    NLU_STATUS_TIMEOUT_MS
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`NLU Status fehlgeschlagen (${response.status}): ${detail}`);
  }
  return response.json();
};

app.get('/healthz', (_req, res) => {
  res.json({
    status: 'ok',
    nlu: NLU_ENDPOINT,
    rag: RAG_ENDPOINT,
    nluConfidenceThreshold: NLU_CONFIDENCE_THRESHOLD,
    nluTimeoutMs: NLU_TIMEOUT_MS,
    nluCacheSize: NLU_CACHE_SIZE,
    nluCacheTtlMs: NLU_CACHE_TTL_MS,
    metricsPort: METRICS_PORT
  });
});

app.get('/readyz', async (_req, res) => {
  try {
    const status = await checkNluStatus();
    return res.json({ status: 'ok', model: status?.model_id || status?.model_file || null });
  } catch (error) {
    return res.status(503).json({ status: 'degraded', error: error.message });
  }
});

app.post('/ask', async (req, res) => {
  const { question, roles: bodyRoles } = req.body || {};
  if (typeof question !== 'string' || !question.trim()) {
    return res.status(400).json({ error: 'question fehlt' });
  }

  const normalizedQuestion = normalizeQuestion(question);
  const headerRoles = req.get('x-roles');
  const roles = [...new Set([...parseRoles(bodyRoles), ...parseRoles(headerRoles)])];

  let nluResult;
  try {
    nluResult = await callNlu(normalizedQuestion);
  } catch (error) {
    console.warn('NLU Anfrage nicht verfuegbar, fallback auf RAG:', error.message);
    const payload = buildRagPayload(normalizedQuestion, roles, {});
    fallbackCount += 1;
    return respondWithRag(res, payload);
  }

  const intentName = nluResult?.intent?.name;
  const confidence = typeof nluResult?.intent?.confidence === 'number' ? nluResult.intent.confidence : null;
  logIntent(intentName, confidence);

  const entityPayload = mapEntitiesToPayload(nluResult?.entities);
  const ragPayload = buildRagPayload(normalizedQuestion, roles, entityPayload);
  const meetsThreshold = Number.isFinite(confidence) && confidence >= NLU_CONFIDENCE_THRESHOLD;
  const shouldFallback = intentName === 'nlu_fallback' || intentName === 'out_of_scope' || !meetsThreshold;

  recordIntentMetrics(intentName, confidence, shouldFallback);

  if (intentName === 'nlu_fallback') {
    console.log('NLU Fallback erkannt, leite an RAG weiter');
    return respondWithRag(res, ragPayload);
  }

  if (intentName === 'out_of_scope') {
    console.log('Intent out_of_scope, leite an RAG weiter');
    return respondWithRag(res, ragPayload);
  }

  if (!meetsThreshold) {
    console.log('Intent unter Confidence-Threshold, RAG Fallback');
    return respondWithRag(res, ragPayload);
  }

  if (intentName === 'ask_rag') {
    return respondWithRag(res, ragPayload);
  }

  if (intentName && STATIC_INTENTS.has(intentName)) {
    return res.json(responses[intentName]);
  }

  if (!shouldFallback) {
    fallbackCount += 1;
  }
  return respondWithRag(res, ragPayload);
});

app.listen(PORT, () => {
  console.log(`Bot-Service laeuft auf Port ${PORT}`);
});

metricsApp.get(METRICS_PATH, (_req, res) => {
  res.type('text/plain').send(renderMetrics());
});

metricsApp.listen(METRICS_PORT, () => {
  console.log(`Metrics Endpoint auf Port ${METRICS_PORT}${METRICS_PATH}`);
});
