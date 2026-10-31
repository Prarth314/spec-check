const $ = s => document.querySelector(s);
let documents = [], selected = new Set(), lastResult = null, busy = false;
function node(tag, text, className) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; }
async function api(path, options) {
  const r = await fetch(path, options);
  if (!r.ok) { let msg = `Request failed (${r.status})`; try { const body = await r.json(); msg = typeof body.detail === 'string' ? body.detail : msg; } catch {} throw new Error(msg); }
  return r.json();
}
function notify(text) { $('#notice').textContent = text; $('#notice').hidden = !text; }
function updateSelection() { $('#selection-count').textContent = selected.size ? `${selected.size} datasheet${selected.size === 1 ? '' : 's'} selected` : 'No datasheets selected'; }
function clearResults() { lastResult = null; $('#results').hidden = true; $('#welcome').hidden = false; }
async function loadDocuments() {
  documents = await api('/api/documents');
  selected = new Set([...selected].filter(id => documents.some(d => d.id === id)));
  const list = $('#documents'); list.replaceChildren(); $('#doc-count').textContent = documents.length;
  if (!documents.length) list.append(node('p', 'Your next project starts with a datasheet.', 'empty-library'));
  for (const doc of documents) {
    const row = node('div', undefined, 'document'), label = node('label', undefined, 'doc-label');
    const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.id = `doc-${doc.id}`; checkbox.checked = selected.has(doc.id); checkbox.setAttribute('aria-label', `Select ${doc.name}`); label.htmlFor = checkbox.id;
    checkbox.addEventListener('change', () => { if (checkbox.checked && selected.size >= 8) { checkbox.checked = false; notify('Select at most 8 datasheets for a question.'); return; } checkbox.checked ? selected.add(doc.id) : selected.delete(doc.id); updateSelection(); });
    label.append(node('span', doc.name, 'doc-name'), node('span', `${doc.pages} pages · ${doc.chunks} chunks`, 'doc-meta'));
    if (doc.warnings.length) { const warning = node('span', `⚠ ${doc.warnings.length} extraction warning${doc.warnings.length > 1 ? 's' : ''}`, 'doc-warning'); warning.title = doc.warnings.join('\n'); label.append(warning); }
    const remove = node('button', '×', 'remove-doc'); remove.type = 'button'; remove.setAttribute('aria-label', `Remove ${doc.name}`);
    remove.addEventListener('click', async () => { remove.disabled = true; try { await api(`/api/documents/${doc.id}`, {method:'DELETE'}); selected.delete(doc.id); clearResults(); await loadDocuments(); } catch (e) { notify(e.message); remove.disabled = false; } });
    row.append(checkbox, label, remove); list.append(row);
  }
  updateSelection();
}
async function uploadFiles(files) {
  if (busy) return notify('Wait for the current question or upload to finish.');
  busy = true; $('#ask-button').disabled = true; notify('');
  for (const file of files) {
    if (file.size > 20 * 1024 * 1024) { notify(`${file.name} exceeds 20 MB.`); continue; }
    $('#upload-status').textContent = `Extracting ${file.name}…`;
    const body = new FormData(); body.append('file', file);
    try {
      const r = await api('/api/documents', {method:'POST',body});
      if (selected.size < 8) selected.add(r.id);
      $('#upload-status').textContent = r.duplicate ? `${file.name} is already in your library.` : `${file.name} · ready to search${r.warnings.length ? ` · ${r.warnings.length} page warning(s)` : ''}`;
    } catch (e) { $('#upload-status').textContent = e.message; }
  }
  try { await loadDocuments(); } catch (e) { notify(e.message); }
  busy = false; $('#ask-button').disabled = false; $('#file-input').value = '';
}
$('#file-input').addEventListener('change', e => uploadFiles([...e.target.files]));
const zone = $('#drop-zone');
zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#file-input').click(); } });
for (const name of ['dragenter','dragover']) zone.addEventListener(name, e => { e.preventDefault(); zone.classList.add('dragging'); });
for (const name of ['dragleave','drop']) zone.addEventListener(name, e => { e.preventDefault(); zone.classList.remove('dragging'); });
zone.addEventListener('drop', e => uploadFiles([...e.dataTransfer.files]));
document.querySelectorAll('[data-question]').forEach(b => b.addEventListener('click', () => { $('#question').value = b.dataset.question; $('#question').focus(); }));
function openSource(docId, page, name) {
  const url = `/api/documents/${encodeURIComponent(docId)}/pdf#page=${page}`;
  $('#source-title').textContent = `${name} · PDF page ${page}`;
  $('#source-image-error').hidden = true; $('#source-image').hidden = false;
  $('#source-image').alt = `${name}, physical PDF page ${page}`;
  $('#source-image').src = `/api/documents/${encodeURIComponent(docId)}/pages/${page}.png`;
  $('#source-open').href = url; $('#source-dialog').showModal();
}
$('#source-image').addEventListener('error', () => { $('#source-image').hidden = true; $('#source-image-error').hidden = false; });
$('#close-dialog').addEventListener('click', () => { $('#source-dialog').close(); });
function renderResult(r) {
  lastResult = r; $('#welcome').hidden = true; $('#results').hidden = false; $('#result-question').textContent = r.question;
  const card = $('#answer-card'); card.replaceChildren();
  const labels = {answered:'Cited answer', partial:'Partial answer · missing evidence', abstained:'Insufficient retrieved evidence', evidence_only:'Evidence search · no model configured', error:'Answer unavailable'};
  card.append(node('div', labels[r.status] || r.status, 'answer-status'));
  for (const claim of r.claims) {
    const p = node('p', claim.text), citations = node('div');
    for (const c of claim.citations) { const b = node('button', `${c.name} · p. ${c.page}`, 'citation'); b.type = 'button'; b.title = c.quote; b.addEventListener('click', () => openSource(c.document_id, c.page, c.name)); citations.append(b); }
    p.append(citations); card.append(p);
  }
  if (r.missing) card.append(node('p', r.missing, 'missing'));
  const list = $('#evidence-list'); list.replaceChildren();
  if (!r.evidence.length) list.append(node('p', 'Try a more specific term or select a different datasheet.'));
  for (const [i,e] of r.evidence.entries()) {
    const details = node('details', undefined, 'evidence'); details.open = i === 0;
    const summary = node('summary', `${e.name} · PDF page ${e.page}`); summary.append(node('small', e.kind === 'table' ? 'TABLE' : 'TEXT'));
    const open = node('button', 'View original page ↗', 'text-button'); open.type = 'button'; open.addEventListener('click', () => openSource(e.document_id, e.page, e.name));
    details.append(summary, node('pre', e.text), open); list.append(details);
  }
  $('#results').scrollIntoView({behavior:'smooth',block:'start'});
}
$('#question-form').addEventListener('submit', async e => {
  e.preventDefault(); if (busy) return;
  if (!selected.size) return notify('Add and select at least one PDF to start your research.');
  const question = $('#question').value.trim(); if (question.length < 3) return notify('Enter a question with at least 3 characters.');
  busy = true; notify(''); $('#ask-button').disabled = true; $('#ask-button').textContent = 'Checking evidence…';
  try { renderResult(await api('/api/ask', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,document_ids:[...selected]})})); }
  catch (e) { notify(e.message); }
  finally { busy = false; $('#ask-button').disabled = false; $('#ask-button').replaceChildren(document.createTextNode('Find the specs '), node('span','↗')); }
});
$('#export-button').addEventListener('click', () => { if (!lastResult) return; const url = URL.createObjectURL(new Blob([JSON.stringify(lastResult,null,2)],{type:'application/json'})); const a = node('a'); a.href = url; a.download = 'spec-check-result.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); });
async function init() {
  try { const h = await api('/api/health'); $('#mode-badge').replaceChildren(node('i'), document.createTextNode(h.llm_configured ? 'LLM configured' : 'Local evidence mode')); await loadDocuments(); }
  catch (e) { $('#mode-badge').textContent = 'Server unavailable'; notify(e.message); }
}
init();
