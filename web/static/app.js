// StreamClips AI Studio Frontend Logic

let currentTab = 'studio';
let sourceMode = 'url';
let uploadedFile = null;
let currentJobId = null;
let ws = null;
let currentModalClip = null;

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  loadSystemStatus();
  loadLibrary();
  loadMemeMoods();
  loadMemes();
});

// ============================================================================
// Tab Navigation
// ============================================================================

function switchTab(tab) {
  currentTab = tab;
  ['studio', 'finder', 'memes', 'library', 'settings'].forEach(t => {
    const btn = document.getElementById(`tab-${t}`);
    const view = document.getElementById(`view-${t}`);
    if (btn && view) {
      if (t === tab) {
        btn.classList.add('active', 'text-white');
        btn.classList.remove('text-slate-400');
        view.classList.remove('hidden');
      } else {
        btn.classList.remove('active', 'text-white');
        btn.classList.add('text-slate-400');
        view.classList.add('hidden');
      }
    }
  });

  if (tab === 'library') loadLibrary();
  if (tab === 'memes') loadMemes();
  lucide.createIcons();
}

// ============================================================================
// WebSocket Realtime Connection
// ============================================================================

function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('StreamClips Realtime WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleWsEvent(payload);
      } catch (err) {
        console.error('WS Parse Error:', err);
      }
    };

    ws.onclose = () => {
      setTimeout(initWebSocket, 2000);
    };

    ws.onerror = (err) => {
      console.warn('WS Error, reconnecting soon:', err);
    };
  } catch (err) {
    console.error('WS Init Error:', err);
  }
}

function handleWsEvent(msg) {
  const type = msg.type;
  const data = msg.data;

  if (type === 'job_update') {
    if (currentJobId && data.id === currentJobId) {
      updateJobProgressUI(data);
    }
  } else if (type === 'job_log') {
    if (currentJobId && data.job_id === currentJobId) {
      appendTerminalLog(data.log);
    }
  } else if (type === 'job_completed') {
    if (currentJobId && data.id === currentJobId) {
      showToast('🎉 Viral clips successfully generated!');
      loadLibrary();
      setTimeout(() => {
        switchTab('library');
      }, 1200);
    }
  } else if (type === 'job_failed') {
    if (currentJobId && data.id === currentJobId) {
      showToast('❌ Job encountered an error: ' + (data.error || 'Check logs'));
    }
  }
}

function updateJobProgressUI(job) {
  const container = document.getElementById('live-progress-container');
  if (container) container.classList.remove('hidden');

  const titleEl = document.getElementById('live-step-title');
  const subEl = document.getElementById('live-sub-step');
  const percentEl = document.getElementById('live-percent');
  const barEl = document.getElementById('live-progress-bar');

  if (titleEl) titleEl.innerText = job.current_step || 'Processing...';
  if (percentEl) percentEl.innerText = `${job.progress || 0}%`;
  if (barEl) barEl.style.width = `${job.progress || 0}%`;

  if (job.status === 'completed') {
    if (subEl) subEl.innerText = 'All clips rendered and saved to library!';
    document.getElementById('start-btn').disabled = false;
  } else if (job.status === 'failed') {
    if (subEl) subEl.innerText = 'Failed: ' + (job.error || 'Unknown error');
    document.getElementById('start-btn').disabled = false;
  }
}

function appendTerminalLog(log) {
  const drawer = document.getElementById('terminal-logs-drawer');
  if (!drawer) return;

  const line = document.createElement('div');
  const kind = log.kind || 'info';

  let colorClass = 'text-slate-300';
  let badge = '>';
  if (kind === 'step') { colorClass = 'text-cyan-400 font-semibold'; badge = '⚡'; }
  else if (kind === 'good') { colorClass = 'text-emerald-400 font-semibold'; badge = '✓'; }
  else if (kind === 'warn') { colorClass = 'text-amber-400'; badge = '!'; }
  else if (kind === 'bad') { colorClass = 'text-red-400 font-bold'; badge = '✗'; }

  line.className = `${colorClass} flex items-start gap-1.5`;
  line.innerHTML = `<span class="text-slate-500">[${log.time || '00:00'}]</span> <span>${badge}</span> <span class="break-words">${escapeHtml(log.msg || '')}</span>`;

  drawer.appendChild(line);
  drawer.scrollTop = drawer.scrollHeight;
}

function toggleTerminalLogs() {
  const drawer = document.getElementById('terminal-logs-drawer');
  if (drawer) {
    drawer.classList.toggle('hidden');
  }
}

// ============================================================================
// Studio Actions & Inputs
// ============================================================================

function setSourceMode(mode) {
  sourceMode = mode;
  const urlBox = document.getElementById('source-url-box');
  const fileBox = document.getElementById('source-file-box');
  const urlBtn = document.getElementById('mode-url-btn');
  const fileBtn = document.getElementById('mode-file-btn');

  if (mode === 'url') {
    urlBox.classList.remove('hidden');
    fileBox.classList.add('hidden');
    urlBtn.className = 'px-3 py-1 rounded-md font-medium bg-violet-600 text-white';
    fileBtn.className = 'px-3 py-1 rounded-md font-medium text-slate-400 hover:text-white';
  } else {
    urlBox.classList.add('hidden');
    fileBox.classList.remove('hidden');
    fileBtn.className = 'px-3 py-1 rounded-md font-medium bg-violet-600 text-white';
    urlBtn.className = 'px-3 py-1 rounded-md font-medium text-slate-400 hover:text-white';
  }
}

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      document.getElementById('stream-url').value = text.trim();
      showToast('URL pasted from clipboard');
    }
  } catch (err) {
    showToast('Clipboard access denied');
  }
}

function fillSample(url, topic) {
  setSourceMode('url');
  document.getElementById('stream-url').value = url;
  if (topic) document.getElementById('stream-topic').value = topic;
  showToast('Sample loaded');
}

function useLocalTestSample() {
  setSourceMode('url');
  document.getElementById('stream-url').value = 'scratch/test_splice.mp4';
  document.getElementById('stream-topic').value = 'Gaming Highlight';
  showToast('Workspace test video loaded');
}

async function handleFileSelect(event) {
  const file = event.target.files[0];
  if (!file) return;

  const dropzone = document.getElementById('dropzone');
  dropzone.innerHTML = `<div class="w-8 h-8 mx-auto rounded-full border-2 border-violet-500 border-t-transparent animate-spin mb-2"></div><p class="text-xs text-slate-300">Uploading ${file.name}...</p>`;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error('Upload failed');
    const data = await res.json();
    uploadedFile = data;

    document.getElementById('uploaded-name').innerText = data.filename;
    document.getElementById('uploaded-meta').innerText = `${data.size_mb} MB · ${data.duration_human}`;
    document.getElementById('dropzone').classList.add('hidden');
    document.getElementById('uploaded-file-info').classList.remove('hidden');
    showToast('File uploaded successfully');
  } catch (err) {
    showToast('Failed to upload video');
    setSourceMode('file');
  }
}

function clearUploadedFile() {
  uploadedFile = null;
  document.getElementById('dropzone').classList.remove('hidden');
  document.getElementById('uploaded-file-info').classList.add('hidden');
  document.getElementById('file-input').value = '';
}

function toggleMemePicker(val) {
  const picker = document.getElementById('specific-meme-container');
  if (val === 'specific') {
    picker.classList.remove('hidden');
  } else {
    picker.classList.add('hidden');
  }
}

// ============================================================================
// Start Video Generation
// ============================================================================

async function startGeneration() {
  let videoSource = '';
  if (sourceMode === 'url') {
    videoSource = document.getElementById('stream-url').value.trim();
  } else {
    if (!uploadedFile || !uploadedFile.path) {
      showToast('Please upload a video file first');
      return;
    }
    videoSource = uploadedFile.path;
  }

  if (!videoSource) {
    showToast('Please enter a video URL or upload a file');
    return;
  }

  const topic = document.getElementById('stream-topic').value.trim() || 'Viral Highlights';
  const clips = parseInt(document.getElementById('clips-count').value || '3');

  // Layout radio
  const layout = document.querySelector('input[name="layout"]:checked')?.value || 'stack';

  // Meme options
  const memeMode = document.getElementById('meme-mode').value;
  let memeVal = 'auto';
  if (memeMode === 'none') memeVal = 'none';
  else if (memeMode === 'specific') memeVal = document.getElementById('specific-meme-select').value;

  const memeStyle = document.getElementById('meme-style').value;
  const language = document.getElementById('language-select').value || null;
  const brain = document.getElementById('brain-select').value || 'auto';
  const section = document.getElementById('section-range').value.trim() || null;
  const minLen = parseInt(document.getElementById('min-length').value || '15');
  const maxLen = parseInt(document.getElementById('max-length').value || '55');
  const fast = document.getElementById('fast-encoding').checked;

  const payload = {
    url: videoSource,
    topic: topic,
    clips: clips,
    layout: layout,
    meme: memeVal,
    meme_style: memeStyle,
    language: language,
    brain: brain,
    section: section,
    min_len: minLen,
    max_len: maxLen,
    fast: fast,
  };

  const btn = document.getElementById('start-btn');
  btn.disabled = true;

  // Clear drawer
  const drawer = document.getElementById('terminal-logs-drawer');
  drawer.innerHTML = '<div class="text-violet-400 font-bold">[00:00] > Starting StreamClips AI pipeline...</div>';

  const container = document.getElementById('live-progress-container');
  container.classList.remove('hidden');
  updateJobProgressUI({ current_step: 'Submitting job to StreamClips engine...', progress: 5 });

  try {
    const res = await fetch('/api/clip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to start clipping');
    }

    const data = await res.json();
    currentJobId = data.job_id;
    showToast('Job started! Processing in background...');
  } catch (err) {
    btn.disabled = false;
    showToast('Error: ' + err.message);
    updateJobProgressUI({ current_step: 'Failed to start', progress: 0, status: 'failed', error: err.message });
  }
}

// ============================================================================
// Stream Finder Tab
// ============================================================================

async function searchStreams() {
  const topic = document.getElementById('finder-topic').value.trim();
  if (!topic) {
    showToast('Please enter a topic or game to search');
    return;
  }

  const when = document.getElementById('finder-when').value;
  const btn = document.getElementById('finder-btn');
  btn.disabled = true;
  btn.innerHTML = `<div class="w-3.5 h-3.5 border-2 border-white border-t-transparent animate-spin rounded-full"></div> Searching...`;

  const grid = document.getElementById('streams-grid');
  grid.innerHTML = `<div class="col-span-full py-12 text-center text-slate-400"><div class="w-8 h-8 mx-auto rounded-full border-2 border-indigo-500 border-t-transparent animate-spin mb-3"></div>Searching live streams and long videos...</div>`;

  try {
    const res = await fetch(`/api/find?topic=${encodeURIComponent(topic)}&when=${when}&count=9`);
    if (!res.ok) throw new Error('Search failed');
    const data = await res.json();

    if (!data.streams || !data.streams.length) {
      grid.innerHTML = `<div class="col-span-full py-12 text-center text-slate-400">No streams found for "${topic}". Try "today" or "week".</div>`;
      return;
    }

    grid.innerHTML = '';
    data.streams.forEach(s => {
      const viewsFmt = s.views ? Number(s.views).toLocaleString() + ' views' : '';
      const durH = s.seconds ? `${Math.floor(s.seconds / 3600)}h ${Math.floor((s.seconds % 3600) / 60)}m` : '';

      const card = document.createElement('div');
      card.className = 'glass-panel rounded-2xl p-4 border border-slate-800 glass-panel-hover flex flex-col justify-between';
      card.innerHTML = `
        <div>
          <div class="flex items-center justify-between text-[11px] mb-2">
            <span class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">${s.platform || 'stream'}</span>
            ${s.live ? '<span class="px-2 py-0.5 rounded bg-red-500/20 text-red-400 font-bold uppercase animate-pulse">LIVE</span>' : ''}
          </div>
          <h3 class="text-xs font-bold text-white line-clamp-2 mb-1" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</h3>
          <p class="text-[11px] font-semibold text-indigo-400 mb-3">${escapeHtml(s.name)}</p>
          <div class="flex items-center justify-between text-[10px] text-slate-400 mb-4">
            <span>${viewsFmt}</span>
            <span>${durH}</span>
          </div>
        </div>
        <button onclick="selectStreamToClip('${s.url}', '${escapeHtml(topic)}')" class="w-full py-2 rounded-xl bg-indigo-600/30 hover:bg-indigo-600 border border-indigo-500/40 text-indigo-200 hover:text-white text-xs font-bold transition-all flex items-center justify-center gap-1.5">
          <i data-lucide="scissors" class="w-3.5 h-3.5"></i>
          <span>Clip This Stream</span>
        </button>
      `;
      grid.appendChild(card);
    });

    lucide.createIcons();
  } catch (err) {
    grid.innerHTML = `<div class="col-span-full py-12 text-center text-red-400">Failed to search streams: ${err.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="search" class="w-3.5 h-3.5"></i> <span>Find Streams</span>`;
    lucide.createIcons();
  }
}

function selectStreamToClip(url, topic) {
  fillSample(url, topic);
  switchTab('studio');
  showToast('Stream loaded into Studio! Click Generate to start clipping.');
}

// ============================================================================
// Indian Meme Vault Tab
// ============================================================================

let memeSearchTimeout = null;

function searchMemesDebounced() {
  clearTimeout(memeSearchTimeout);
  memeSearchTimeout = setTimeout(() => {
    loadMemes();
  }, 300);
}

async function loadMemeMoods() {
  try {
    const res = await fetch('/api/memes/moods');
    if (!res.ok) return;
    const moods = await res.json();
    const container = document.getElementById('meme-mood-filters');
    if (!container) return;

    container.innerHTML = `<button onclick="filterMemeMood('')" class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-pink-600 text-white meme-mood-btn" data-mood="">All (567)</button>`;
    moods.forEach(m => {
      container.innerHTML += `<button onclick="filterMemeMood('${m}')" class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700 meme-mood-btn" data-mood="${m}">${m}</button>`;
    });
  } catch (err) {
    console.warn(err);
  }
}

let activeMemeMood = '';

function filterMemeMood(mood) {
  activeMemeMood = mood;
  document.querySelectorAll('.meme-mood-btn').forEach(btn => {
    if (btn.getAttribute('data-mood') === mood) {
      btn.className = 'px-2.5 py-1 rounded-full text-[11px] font-semibold bg-pink-600 text-white meme-mood-btn';
    } else {
      btn.className = 'px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700 meme-mood-btn';
    }
  });
  loadMemes();
}

async function loadMemes() {
  const query = document.getElementById('meme-search-input')?.value.trim() || '';
  const grid = document.getElementById('memes-grid');
  if (!grid) return;

  grid.innerHTML = `<div class="col-span-full py-12 text-center text-slate-500"><div class="w-6 h-6 mx-auto rounded-full border-2 border-pink-500 border-t-transparent animate-spin mb-2"></div>Loading memes...</div>`;

  try {
    const res = await fetch(`/api/memes?query=${encodeURIComponent(query)}&mood=${encodeURIComponent(activeMemeMood)}&limit=35`);
    const data = await res.json();

    if (!data.memes || !data.memes.length) {
      grid.innerHTML = `<div class="col-span-full py-12 text-center text-slate-400">No memes found matching "${query}".</div>`;
      return;
    }

    grid.innerHTML = '';
    data.memes.forEach(m => {
      const card = document.createElement('div');
      card.className = 'glass-panel rounded-xl p-3 border border-slate-800 flex flex-col justify-between';
      card.innerHTML = `
        <div>
          <div class="aspect-video bg-black rounded-lg overflow-hidden relative mb-2 group">
            ${m.video_url ? `
              <video src="${m.video_url}" preload="metadata" muted onmouseover="this.play()" onmouseout="this.pause();this.currentTime=0;" class="w-full h-full object-cover"></video>
              <div class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                <i data-lucide="play" class="w-6 h-6 text-pink-400 fill-pink-400"></i>
              </div>
            ` : '<div class="w-full h-full flex items-center justify-center text-slate-600"><i data-lucide="image" class="w-6 h-6"></i></div>'}
          </div>
          <h4 class="text-xs font-bold text-white line-clamp-1" title="${escapeHtml(m.title)}">${escapeHtml(m.title)}</h4>
          <div class="flex flex-wrap gap-1 mt-1 mb-2">
            ${(m.moods || []).slice(0, 2).map(md => `<span class="text-[9px] px-1.5 py-0.2 rounded bg-pink-500/10 text-pink-300 font-medium">${md}</span>`).join('')}
          </div>
        </div>
        <button onclick="useMemeInStudio('${m.id}')" class="w-full py-1.5 rounded-lg bg-pink-600/20 hover:bg-pink-600 text-pink-300 hover:text-white text-[11px] font-semibold transition-all">
          Use This Meme
        </button>
      `;
      grid.appendChild(card);
    });

    lucide.createIcons();
  } catch (err) {
    grid.innerHTML = `<div class="col-span-full py-12 text-center text-red-400">Failed to load memes</div>`;
  }
}

function useMemeInStudio(memeId) {
  document.getElementById('meme-mode').value = 'specific';
  toggleMemePicker('specific');
  
  // Update or append option
  const sel = document.getElementById('specific-meme-select');
  let found = false;
  for (let i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === memeId) {
      sel.selectedIndex = i;
      found = true;
      break;
    }
  }
  if (!found) {
    const opt = document.createElement('option');
    opt.value = memeId;
    opt.text = memeId;
    opt.selected = true;
    sel.add(opt);
  }

  switchTab('studio');
  showToast(`Meme reaction "${memeId}" selected for your next clip!`);
}

// ============================================================================
// Video Library Tab
// ============================================================================

async function loadLibrary() {
  const container = document.getElementById('library-container');
  if (!container) return;

  try {
    const res = await fetch('/api/library');
    const projects = await res.json();

    const badge = document.getElementById('library-badge');
    const totalClips = projects.reduce((acc, p) => acc + (p.clips_count || 0), 0);
    if (badge) badge.innerText = totalClips;

    if (!projects || !projects.length) {
      container.innerHTML = `
        <div class="glass-panel rounded-2xl p-12 text-center border border-slate-800">
          <div class="w-12 h-12 mx-auto rounded-full bg-slate-800 text-slate-500 flex items-center justify-center mb-3">
            <i data-lucide="film" class="w-6 h-6"></i>
          </div>
          <h3 class="text-sm font-bold text-white mb-1">No generated clips yet</h3>
          <p class="text-xs text-slate-400 mb-4">Run your first video in Studio to see ready-to-post 9:16 vertical clips here.</p>
          <button onclick="switchTab('studio')" class="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-xs font-bold text-white">Create Clips in Studio</button>
        </div>
      `;
      lucide.createIcons();
      return;
    }

    container.innerHTML = '';
    projects.forEach(proj => {
      const projCard = document.createElement('div');
      projCard.className = 'glass-panel rounded-2xl p-6 border border-slate-800 space-y-4';

      let clipsHtml = '';
      proj.clips.forEach(clip => {
        clipsHtml += `
          <div class="bg-slate-950/70 border border-slate-800/80 rounded-xl overflow-hidden flex flex-col justify-between group hover:border-violet-500/40 transition-all">
            <!-- 9:16 Video Player Container -->
            <div class="aspect-[9/16] bg-black relative overflow-hidden flex items-center justify-center">
              <video src="${clip.video_url}" preload="metadata" controls class="w-full h-full object-cover"></video>
              <div class="absolute top-2 left-2 px-2 py-0.5 rounded-full bg-black/60 backdrop-blur-md text-[10px] font-bold text-emerald-400 border border-emerald-500/30">
                ${clip.score}/100
              </div>
              ${clip.meme ? `
                <div class="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-pink-600/80 backdrop-blur-md text-[9px] font-bold text-white">
                  🎭 ${escapeHtml(clip.meme)}
                </div>
              ` : ''}
            </div>

            <!-- Clip Info -->
            <div class="p-3.5 space-y-2">
              <div class="flex items-center justify-between text-[10px] text-slate-400">
                <span class="uppercase tracking-wider font-bold text-violet-400">${clip.type}</span>
                <span>${clip.seconds ? Math.round(clip.seconds) + 's' : ''}</span>
              </div>
              <h4 class="text-xs font-bold text-white line-clamp-1" title="${escapeHtml(clip.title)}">${escapeHtml(clip.title)}</h4>
              
              <!-- Action Buttons -->
              <div class="grid grid-cols-2 gap-1.5 pt-1">
                <button onclick="copyCaption('${escapeJs(clip.caption)}', '${escapeJs(clip.hashtags.join(' '))}')" class="py-1.5 px-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-200 text-[10px] font-semibold border border-slate-700/60 flex items-center justify-center gap-1">
                  <i data-lucide="copy" class="w-3 h-3"></i>
                  <span>Copy Caption</span>
                </button>
                <a href="${clip.download_url}" download class="py-1.5 px-2 rounded-lg bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white text-[10px] font-semibold border border-emerald-500/30 flex items-center justify-center gap-1">
                  <i data-lucide="download" class="w-3 h-3"></i>
                  <span>Download</span>
                </a>
              </div>
            </div>
          </div>
        `;
      });

      projCard.innerHTML = `
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-violet-400">${escapeHtml(proj.creator)}</span>
              <span class="text-slate-600">·</span>
              <span class="text-xs text-slate-400">${proj.date}</span>
              <span class="text-slate-600">·</span>
              <span class="px-2 py-0.2 rounded-full text-[10px] bg-slate-800 text-slate-300">${proj.topic}</span>
            </div>
            <h3 class="text-sm font-bold text-white mt-0.5">${escapeHtml(proj.title)}</h3>
          </div>
          <span class="text-xs font-bold text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-lg border border-emerald-500/20 self-start sm:self-auto">
            ${proj.clips_count} Ready Clips
          </span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          ${clipsHtml}
        </div>
      `;

      container.appendChild(projCard);
    });

    lucide.createIcons();
  } catch (err) {
    console.error('Failed to load library:', err);
  }
}

function copyCaption(caption, hashtags) {
  const full = `${caption}\n${hashtags}`;
  navigator.clipboard.writeText(full).then(() => {
    showToast('📋 Ready-to-post caption & hashtags copied!');
  }).catch(() => {
    showToast('Failed to copy');
  });
}

// ============================================================================
// Settings & Diagnostics
// ============================================================================

async function loadSystemStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    const statusEl = document.getElementById('engine-status');
    if (statusEl) statusEl.innerText = data.status === 'ready' ? 'Ready' : 'Check Setup';

    const memeCountEl = document.getElementById('header-meme-count');
    if (memeCountEl) memeCountEl.innerText = data.memes?.total_templates || '567';

    const diagList = document.getElementById('system-diag-list');
    if (diagList) {
      const items = [
        { name: 'FFmpeg Audio & Video Processor', ok: data.tools?.ffmpeg },
        { name: 'FFprobe Media Inspector', ok: data.tools?.ffprobe },
        { name: 'yt-dlp Stream Downloader', ok: data.tools?.yt_dlp || data.tools?.['yt-dlp'] },
        { name: 'JavaScript Runtime (Deno/Node)', ok: data.tools?.javascript },
        { name: 'OpenCV Face Detection Model', ok: data.tools?.face_model },
        { name: 'Indian Memes Catalog (567 templates)', ok: data.memes?.total_templates > 0 },
      ];
      diagList.innerHTML = items.map(it => `
        <div class="p-3 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
          <span class="text-slate-300 font-medium">${it.name}</span>
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${it.ok ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}">
            ${it.ok ? 'INSTALLED' : 'MISSING'}
          </span>
        </div>
      `).join('');
    }
  } catch (err) {
    console.warn('Status check failed:', err);
  }
}

async function saveGeminiKey() {
  const key = document.getElementById('gemini-key-input')?.value.trim();
  if (!key) return;

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: key }),
    });
    if (res.ok) {
      showToast('Gemini API Key saved successfully');
      document.getElementById('gemini-status-text').innerText = '✓ Key is active and configured for highlight picking';
    }
  } catch (err) {
    showToast('Failed to save API key');
  }
}

// ============================================================================
// Utilities
// ============================================================================

function showToast(text) {
  const toast = document.getElementById('toast');
  const toastText = document.getElementById('toast-text');
  if (toast && toastText) {
    toastText.innerText = text;
    toast.classList.remove('hidden');
    setTimeout(() => {
      toast.classList.add('hidden');
    }, 3500);
  }
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeJs(str) {
  return String(str || '')
    .replace(/'/g, "\\'")
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n');
}
