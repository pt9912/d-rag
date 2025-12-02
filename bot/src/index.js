import express from 'express';
import fetch from 'node-fetch';
import morgan from 'morgan';

const app = express();
app.use(express.json());
app.use(morgan('dev'));

const PORT = process.env.PORT || 3978;
const NLU_ENDPOINT = process.env.NLU_ENDPOINT || 'http://rasa:5005';
const RAG_ENDPOINT = process.env.RAG_ENDPOINT || 'http://rag-service:8000';

app.get('/healthz', (_req, res) => {
  res.json({ status: 'ok', nlu: NLU_ENDPOINT, rag: RAG_ENDPOINT });
});

app.post('/ask', async (req, res) => {
  const { question, roles: bodyRoles } = req.body;
  if (!question) {
    return res.status(400).json({ error: 'question fehlt' });
  }

  const headerRoles = req.get('x-roles');
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

  const roles = [...new Set([...parseRoles(bodyRoles), ...parseRoles(headerRoles)])];
  const payload = roles.length ? { question, roles } : { question };

  try {
    const response = await fetch(`${RAG_ENDPOINT}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const detail = await response.text();
      return res.status(502).json({ error: 'RAG Anfrage fehlgeschlagen', detail });
    }

    const data = await response.json();
    res.json({ answer: data.answer, contexts: data.contexts });
  } catch (error) {
    res.status(500).json({ error: 'Interner Fehler', detail: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Bot-Service läuft auf Port ${PORT}`);
});
