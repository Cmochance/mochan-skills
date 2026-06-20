#!/usr/bin/env node
// codex-e2e-test driver —— 通过 CDP 驱动真实 Codex Desktop 跑一轮对话并读回结果,
// 用于对 codex-app-transfer 的 Codex 集成做 E2E/冒烟测试。零依赖(Node ≥20 内建 WebSocket)。
//
// 可行性 + 选择子(composer=ProseMirror / submit=size-token-button-compose 或 fiber
// handleSubmit / 完成=fiber isSubmitting / 移除会话=thread 行 fiber onArchive)均 CDP 实证。
//
// 安全闸:run-isolated 归档前会确认目标 thread-id **不在运行前已存在的集合**里,
// 证明是本工具新建的会话才归档 —— 绝不动用户已有会话。
//
// 用法:
//   node codex-driver.mjs status
//   node codex-driver.mjs run-isolated "<prompt>" [--timeout 180] [--keep]
//   node codex-driver.mjs run-here     "<prompt>" [--timeout 180]   (当前会话,绝不归档)
//   node codex-driver.mjs archive <thread-id>
// 输出:最后一行是 JSON 结果(machine-readable),前面是进度日志(stderr)。

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const log = (...a) => console.error('[codex-e2e]', ...a);
const out = (obj) => console.log(JSON.stringify(obj));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function portFile() {
  // macOS。其它平台按需扩展。
  return path.join(os.homedir(), 'Library/Application Support/Codex/DevToolsActivePort');
}
function resolvePort() {
  const f = portFile();
  if (!fs.existsSync(f)) {
    throw new Error(
      `找不到 DevToolsActivePort(${f})。Codex 需经 transfer 启动并带 --remote-debugging-port;` +
        `先在 transfer 设置里开任一 CDP 功能(如远程控制/主题/额度)再重启 Codex。`,
    );
  }
  const port = fs.readFileSync(f, 'utf8').split('\n')[0].trim();
  if (!port || port === '0') throw new Error('DevToolsActivePort 端口未就绪(0),Codex 可能还在启动,稍候重试。');
  return port;
}

async function connect() {
  const port = resolvePort();
  const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = list.find((t) => t.type === 'page' && (t.url || '').includes('index.html') && !(t.url || '').includes('avatar-overlay'));
  if (!page) throw new Error('CDP /json/list 没有 Codex 主窗口页(index.html)。Codex 在运行吗?');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pend = {};
  let id = 0;
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend[m.id]) {
      pend[m.id](m);
      delete pend[m.id];
    }
  });
  await new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', () => rej(new Error('CDP WebSocket 连接失败')));
  });
  const evalJS = (expr, awaitPromise = false) =>
    new Promise((res, rej) => {
      const i = ++id;
      pend[i] = (m) => {
        if (m.error) return rej(new Error(JSON.stringify(m.error)));
        const r = m.result;
        if (r.exceptionDetails) return rej(new Error('JS 异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 300)));
        res(r.result?.value);
      };
      ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true, awaitPromise } }));
    });
  return { ws, evalJS, port };
}

// ---- 注入页里的小工具 + 各操作 JS ----
const JS_HELPERS = `
function __fiberOf(el){ if(!el) return null; for(var k in el){ if(k.indexOf('__reactFiber$')===0) return el[k]; } return null; }
function __composer(){ return document.querySelector('.ProseMirror'); }
function __submitting(){
  var pm=__composer(); if(!pm) return null;
  var el=pm,f=null; while(el && !(f=__fiberOf(el))) el=el.parentElement;
  var d=0; while(f && d<22){ var p=f.memoizedProps; if(p && typeof p.isSubmitting==='boolean') return p.isSubmitting; f=f.return; d++; }
  return null;
}
function __activeThreadId(){
  var r=document.querySelector('[data-app-action-sidebar-thread-active="true"]');
  return r ? r.getAttribute('data-app-action-sidebar-thread-id') : null;
}
function __allThreadIds(){
  return Array.from(document.querySelectorAll('[data-app-action-sidebar-thread-id]'))
    .map(function(e){ return e.getAttribute('data-app-action-sidebar-thread-id'); }).filter(Boolean);
}
`;

const JS_STATUS = `${JS_HELPERS}
(function(){
  var pm=__composer();
  return { composerPresent: !!pm, submitting: __submitting(), activeThreadId: __activeThreadId(), threadCount: __allThreadIds().length };
})()`;

const JS_ALL_IDS = `${JS_HELPERS}\n(function(){ return __allThreadIds(); })()`;

const JS_NEW_CHAT = `
(function(){
  var b=document.querySelector('[aria-label^="Start new chat"]')||document.querySelector('[aria-label*="new chat" i]');
  if(b){ b.click(); return true; } return false;
})()`;

function jsSetInput(text) {
  const lit = JSON.stringify(text);
  return `${JS_HELPERS}
(function(){
  var pm=__composer(); if(!pm) return {ok:false,err:'no composer'};
  var TEXT=${lit};
  function norm(s){ return (s||'').replace(/\\s+/g,''); }
  pm.focus();
  try{ var sel=window.getSelection(); sel.removeAllRanges(); var r=document.createRange(); r.selectNodeContents(pm); sel.addRange(r); }catch(e){}
  try{ document.execCommand('insertText', false, TEXT); }catch(e){}
  if(norm(pm.textContent)!==norm(TEXT)){
    try{ var s2=window.getSelection(); s2.removeAllRanges(); var r2=document.createRange(); r2.selectNodeContents(pm); s2.addRange(r2); document.execCommand('delete'); }catch(e){}
    try{ pm.dispatchEvent(new InputEvent('beforeinput',{inputType:'insertText',data:TEXT,bubbles:true,cancelable:true})); pm.dispatchEvent(new InputEvent('input',{inputType:'insertText',data:TEXT,bubbles:true})); }catch(e){}
  }
  return { ok: norm(pm.textContent)===norm(TEXT), text: pm.textContent };
})()`;
}

const JS_SUBMIT = `${JS_HELPERS}
(function(){
  var sb=document.querySelector('button[class*="size-token-button-compose"]');
  if(sb && !(sb.disabled===true || sb.getAttribute('aria-disabled')==='true')){ sb.click(); return {via:'button'}; }
  var pm=__composer(); if(!pm) return {via:'none',err:'no composer'};
  var el=pm,f=null; while(el && !(f=__fiberOf(el))) el=el.parentElement;
  var d=0,hs=null; while(f && d<24){ var p=f.memoizedProps; if(p && typeof p.handleSubmit==='function'){ hs=p.handleSubmit; break; } f=f.return; d++; }
  if(hs){ try{ hs(); return {via:'handleSubmit'}; }catch(e){ return {via:'handleSubmit',err:String(e)}; } }
  return {via:'none'};
})()`;

const JS_READ = `${JS_HELPERS}
(function(){
  var out={ submitting: __submitting(), activeThreadId: __activeThreadId(), reply: null, hasFinal: false, rawTail: null };
  var ub=document.querySelectorAll('[data-user-message-bubble]');
  var lastUser=ub.length?ub[ub.length-1]:null;
  // 策略①(最精准 + 完成信号):Codex 给**最终**assistant 消息打 data-local-conversation-final-assistant
  // 标记 —— 它在最终答案渲染好后才出现(Thinking 阶段不在),是比 isSubmitting 更可靠的完成信号。
  // **必须在最新用户消息之后**(compareDocumentPosition)才算本轮,否则是上一轮残留旧答案,
  // 会让新 prompt 仍在 thinking 时误判完成、抓到旧答案。克隆后剥用户气泡 + 时间戳叶子。
  var fa=document.querySelectorAll('[data-local-conversation-final-assistant]');
  if(fa.length){
    var faNode=fa[fa.length-1];
    var isAfter = !lastUser || (lastUser.compareDocumentPosition(faNode) & 4); // FOLLOWING
    if(isAfter){
      var clone=faNode.cloneNode(true);
      clone.querySelectorAll('[data-user-message-bubble]').forEach(function(n){ n.remove(); });
      clone.querySelectorAll('*').forEach(function(n){ if(!n.children.length && /^\s*\d{1,2}:\d{2}\s?(AM|PM)\s*$/i.test(n.textContent||'')) n.remove(); });
      var t=(clone.innerText||'').trim();
      if(t){ out.reply=t; out.hasFinal=true; }
    }
  }
  // 策略②(兜底):data-user-message-bubble 定位 +「含该气泡但**不含 composer**」滚动容器
  // (排除 composer 底栏 Approve/模型选择/Thinking 噪声),气泡之后即 assistant 区。
  if(lastUser){
    var cont=lastUser, picked=null;
    for(var i=0;i<16 && cont.parentElement;i++){
      var c=cont.parentElement;
      if(c.querySelector('.ProseMirror')) break;
      cont=c;
      var r=c.getBoundingClientRect();
      if(r.width>380 && c.scrollHeight>c.clientHeight+20) picked=c;
    }
    var box=picked||cont;
    var full=box.innerText||''; var key=(lastUser.innerText||'').slice(0,60); var idx=key?full.lastIndexOf(key):-1;
    var tail = idx>=0 ? full.slice(idx + (lastUser.innerText||'').length) : null;
    out.rawTail = tail ? tail.slice(0,500) : null;
    if(out.reply==null) out.reply = tail; // 无 final 标记时退回尾文本
  }
  return out;
})()`;

function jsArchive(threadId) {
  const lit = JSON.stringify(threadId);
  return `${JS_HELPERS}
(function(){
  var ID=${lit};
  var row=document.querySelector('[data-app-action-sidebar-thread-id="'+ID.replace(/"/g,'\\\\"')+'"]');
  if(!row) return {ok:false, err:'row not found (already gone?)'};
  var el=row,f=null; while(el && !(f=__fiberOf(el))) el=el.parentElement;
  var d=0; while(f && d<16){ var p=f.memoizedProps; if(p && typeof p.onArchive==='function'){ try{ p.onArchive(); return {ok:true, via:'onArchive'}; }catch(e){ return {ok:false, err:String(e)}; } } f=f.return; d++; }
  return {ok:false, err:'onArchive handler not found on row fiber'};
})()`;
}

function cleanReply(raw) {
  if (!raw) return '';
  return raw
    .split('\n')
    // 剥行尾粘连的时间戳(final-assistant innerText 常把正文与 "10:58 PM" 拼成一行无换行,
    // 且全数字时 "9911:01 PM" 无词边界 → 不能用 \b,贪婪匹配行尾时间戳即可切开)
    .map((l) => l.trim().replace(/\s*\d{1,2}:\d{2}\s?(AM|PM)\s*$/i, '').trim())
    .filter(
      (l) =>
        l &&
        !/^\d{1,2}:\d{2}\s?(AM|PM)$/i.test(l) && // 整行时间戳
        !l.startsWith('Worked for ') && // 工时状态
        l !== 'Thinking' && // 流式思考占位
        l !== 'Approve for me', // 批准按钮(理论已被 composer 排除,双保险)
    )
    .join('\n');
}

// 轮询直到「最终 assistant 文本就绪」或超时。
// 完成信号优先用 data-local-conversation-final-assistant(最终答案渲染才出),其次
// submitting===false —— **均要求非空文本**:isSubmitting 在 Thinking/streaming 阶段会
// 提前读 false,只看它会把"还在思考"当完成、抓到空串。空文本(纯思考/等批准/纯工具)
// 不早退,等到 timeout 收尾并回传 rawTail 让调用方看到真实状态。
async function readUntilDone(evalJS, { timeoutMs, preIds }) {
  const deadline = Date.now() + timeoutMs;
  let lastSeen = '';
  let stable = 0;
  let sawRunning = false;
  let testThreadId = null;
  let lastRawTail = '';
  while (Date.now() < deadline) {
    await sleep(1200);
    let snap;
    try {
      snap = await evalJS(JS_READ);
    } catch (e) {
      log('read 失败(可能 Codex 重载),重试:', e.message);
      continue;
    }
    if (snap.submitting === true) sawRunning = true;
    // 捕获本次新建会话的 id(必须是运行前不存在的 → 证明是新建的)
    if (!testThreadId && snap.activeThreadId && preIds && !preIds.has(snap.activeThreadId)) {
      testThreadId = snap.activeThreadId;
      log('捕获到新建会话 thread-id:', testThreadId);
    }
    if (snap.rawTail) lastRawTail = snap.rawTail;
    const reply = cleanReply(snap.reply || '');
    if (reply === lastSeen) stable += 1;
    else {
      stable = 0;
      lastSeen = reply;
    }
    const doneWithText = lastSeen.length > 0 && stable >= 2 && (snap.hasFinal || snap.submitting === false);
    if (doneWithText) {
      return { reply: lastSeen, threadId: testThreadId, timedOut: false, rawTail: lastRawTail, sawRunning };
    }
  }
  return { reply: lastSeen, threadId: testThreadId, timedOut: true, rawTail: lastRawTail, sawRunning };
}

async function ensureComposer(evalJS) {
  const st = await evalJS(JS_STATUS);
  if (st.submitting === true) throw new Error('Codex 桌面端有一轮正在进行(submitting=true),请等它结束再测。');
  if (!st.composerPresent) {
    log('composer 不在场,点新建对话…');
    await evalJS(JS_NEW_CHAT);
    await sleep(1500);
    const st2 = await evalJS(JS_STATUS);
    if (!st2.composerPresent) throw new Error('无法获得 composer(当前视图无输入框且新建失败)。');
  }
}

async function inject(evalJS, prompt) {
  const set = await evalJS(jsSetInput(prompt));
  if (!set.ok) throw new Error('灌入 prompt 失败/内容不一致(防残留草稿):' + (set.err || set.text || ''));
  await sleep(350);
  const sub = await evalJS(JS_SUBMIT);
  if (sub.via === 'none' || sub.err) throw new Error('提交失败:' + (sub.err || 'no submit path'));
  log('已提交(via=' + sub.via + ')');
}

async function cmdStatus() {
  const { ws, evalJS, port } = await connect();
  const st = await evalJS(JS_STATUS);
  ws.close();
  out({ ok: true, port, ...st });
}

async function cmdRunIsolated(prompt, { timeoutMs, keep }) {
  const { ws, evalJS } = await connect();
  try {
    const preIds = new Set(await evalJS(JS_ALL_IDS));
    log(`运行前已有会话 ${preIds.size} 个(归档安全闸基线)`);
    log('新建独立测试会话…');
    await evalJS(JS_NEW_CHAT);
    await sleep(1500);
    await ensureComposer(evalJS);
    await inject(evalJS, prompt);
    const res = await readUntilDone(evalJS, { timeoutMs, preIds });
    let archived = false;
    let archiveNote = '';
    if (keep) {
      archiveNote = '--keep 指定,保留测试会话(未归档)';
    } else if (!res.threadId) {
      archiveNote = '⚠️ 未捕获到「运行前不存在」的新 thread-id → 跳过归档(安全闸:不确定是新建会话,绝不动已有会话)。如确需清理请手动处理。';
    } else if (preIds.has(res.threadId)) {
      archiveNote = `⚠️ thread-id ${res.threadId} 在运行前已存在 → 跳过归档(安全闸)。`;
    } else {
      const a = await evalJS(jsArchive(res.threadId));
      archived = a.ok === true;
      archiveNote = archived ? `已归档测试会话 ${res.threadId}` : `归档失败:${a.err}`;
      if (archived) {
        await sleep(600);
        const stillThere = new Set(await evalJS(JS_ALL_IDS)).has(res.threadId);
        archiveNote += stillThere ? '(但仍在列表,未确认移除)' : '(已从列表移除,确认)';
      }
    }
    log(archiveNote);
    out({
      ok: true,
      mode: 'isolated',
      reply: res.reply,
      threadId: res.threadId,
      timedOut: res.timedOut,
      archived,
      archiveNote,
      ...(res.reply
        ? {}
        : {
            rawTail: res.rawTail || null,
            note: res.timedOut
              ? '未在超时内拿到最终 assistant 文本(模型可能仍在思考 / 等桌面批准 / 纯工具轮)。见 rawTail。'
              : '完成但无文本输出。见 rawTail。',
          }),
    });
  } finally {
    ws.close();
  }
}

async function cmdRunHere(prompt, { timeoutMs }) {
  const { ws, evalJS } = await connect();
  try {
    await ensureComposer(evalJS);
    const before = await evalJS(JS_STATUS);
    await inject(evalJS, prompt);
    // run-here 绝不归档任何会话(用户已有会话)
    const res = await readUntilDone(evalJS, { timeoutMs, preIds: null });
    out({
      ok: true,
      mode: 'here',
      reply: res.reply,
      threadId: before.activeThreadId,
      timedOut: res.timedOut,
      archived: false,
      archiveNote: 'run-here 模式不归档任何会话',
      ...(res.reply ? {} : { rawTail: res.rawTail || null, note: '未拿到最终文本,见 rawTail。' }),
    });
  } finally {
    ws.close();
  }
}

async function cmdArchive(threadId) {
  const { ws, evalJS } = await connect();
  try {
    const a = await evalJS(jsArchive(threadId));
    out({ ok: a.ok === true, threadId, ...a });
  } finally {
    ws.close();
  }
}

// ---- CLI ----
const [cmd, ...rest] = process.argv.slice(2);
function flag(name, def) {
  const i = rest.indexOf('--' + name);
  if (i < 0) return def;
  return name === 'keep' ? true : rest[i + 1];
}
const positional = rest.filter((a, i) => !a.startsWith('--') && !(i > 0 && rest[i - 1]?.startsWith('--') && rest[i - 1] !== '--keep'));
const prompt = positional[0];
const timeoutMs = (Number(flag('timeout', 180)) || 180) * 1000;
const keep = flag('keep', false);

try {
  if (cmd === 'status') await cmdStatus();
  else if (cmd === 'run-isolated') {
    if (!prompt) throw new Error('用法: run-isolated "<prompt>"');
    await cmdRunIsolated(prompt, { timeoutMs, keep });
  } else if (cmd === 'run-here') {
    if (!prompt) throw new Error('用法: run-here "<prompt>"');
    await cmdRunHere(prompt, { timeoutMs });
  } else if (cmd === 'archive') {
    if (!prompt) throw new Error('用法: archive <thread-id>');
    await cmdArchive(prompt);
  } else {
    throw new Error(`未知命令 "${cmd}"。可用:status | run-isolated | run-here | archive`);
  }
  process.exit(0);
} catch (e) {
  out({ ok: false, error: e.message });
  process.exit(1);
}
