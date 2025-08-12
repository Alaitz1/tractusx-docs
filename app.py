#!/usr/bin/env python3
from __future__ import annotations

import os
import time
import threading
import contextlib
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, send_from_directory, request, Response, render_template_string, redirect, url_for, abort

# ============================
# Configuración
# ============================
OUTPUT_DIR = os.getenv("OUT", "tractusx-docs")
INTERVAL_HOURS = int(os.getenv("INTERVAL_HOURS", "24"))
ADMIN_SECRET = os.getenv("ADMIN_SECRET")  # Protege /run si se define
ADMIN_FIRST = os.getenv("ADMIN_FIRST", "0") == "1"
FAST_MODE = os.getenv("FAST_MODE", "1") == "1"  # por defecto rápido
MAX_WORKERS = int(os.getenv("WORKERS", "12"))     # paralelismo en modo rápido
DEFAULT_PATHS = [p.strip() for p in os.getenv("PATHS", "docs,documentation,doc,website/docs").split(",") if p.strip()]
ORG = os.getenv("ORG", "eclipse-tractusx")
MONTHS_BACK = int(os.getenv("MONTHS_BACK", "6"))
GITHUB_TOKEN_ENV = os.getenv("GITHUB_TOKEN")

app = Flask(__name__)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================
# Utilidades
# ============================
@contextlib.contextmanager
def temp_env(var: str, value: str | None):
    old = os.environ.get(var)
    if value is None:
        os.environ.pop(var, None)
    else:
        os.environ[var] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old

def mask_token(tok: str | None) -> str:
    if not tok:
        return "(ninguno)"
    return f"***{tok[-4:]}" if len(tok) >= 8 else "***"

# ---- HTTP helpers (modo rápido)

def _http_get(url: str, token: str | None):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _months_ago_iso(months_back: int) -> str:
    from datetime import datetime, timezone
    from calendar import monthrange
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    day = min(now.day, monthrange(y, m)[1])
    dt_cut = now.replace(year=y, month=m, day=day)
    return dt_cut.strftime("%Y-%m-%dT%H:%M:%SZ")


def _list_repos(org: str, token: str | None):
    page = 1
    while True:
        url = f"https://api.github.com/orgs/{urllib.parse.quote(org)}/repos?per_page=100&page={page}&type=public"
        data = _http_get(url, token)
        if not data:
            break
        for r in data:
            yield r
        page += 1


def _fetch_tree_paths(org: str, repo: str, branch: str, token: str | None):
    # Un request por repo; listado recursivo de archivos
    url = f"https://api.github.com/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}/git/trees/{urllib.parse.quote(branch)}?recursive=1"
    data = _http_get(url, token)
    nodes = data.get("tree", []) if isinstance(data, dict) else []
    return [n.get("path") for n in nodes if n.get("type") == "blob"]

# ============================
# Generación de índice (árbol navegable) y visor
# ============================

def write_index_and_viewer(out_dir: str, org: str):
    index_path = os.path.join(out_dir, "index.html")
    viewer_path = os.path.join(out_dir, "viewer.html")

    INDEX_HTML = f"""<!doctype html>
<html lang="es">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Índice de documentación — Tractus-X</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;margin:2rem;background:#0b1020;color:#e5e7eb}}
h1{{margin-bottom:1rem}}
.repo{{margin:0 0 1.25rem;padding:1rem;border:1px solid #243148;border-radius:12px;background:#12182c}}
a{{color:#8ab4f8;text-decoration:none}}a:hover{{text-decoration:underline}}
ul{{margin:.25rem 0 .75rem 1.25rem}}
small{{color:#a3a3a3}}
.badge{{display:inline-block;border:1px solid #243148;border-radius:8px;padding:.1rem .5rem;margin-left:.5rem;color:#cbd5e1;background:#0b1020}}
#q{{background:#0b1020;border:1px solid #243148;border-radius:8px;padding:.5rem .75rem;color:#e5e7eb;width:100%;max-width:480px}}
.group{{margin:.5rem 0 .25rem;font-weight:600;color:#e2e8f0}}
.file{{font-size:.95rem}}
.btn{{border:1px solid #243148;border-radius:8px;background:#0b1020;color:#e5e7eb;padding:.15rem .4rem;cursor:pointer}}
ul.tree{{list-style:none;margin:.25rem 0 .25rem .25rem;padding-left:.5rem}}
li.dir{{margin:.15rem 0}}
li.file{{margin:.1rem 0}}
.header{{display:flex;align-items:center;gap:.35rem}}
</style>
<h1>Índice de documentación — Tractus-X</h1>
<p><small>Org: {org}. Generado en modo {'rápido' if FAST_MODE else 'completo'}.</small></p>
<input id="q" type="search" placeholder="Filtrar por repo, carpeta o fichero…" autocomplete="off"/>
<div id="list"></div>
<script>
(async () => {{
  const res = await fetch('tree.json');
  const tree = await res.json();
  const listEl = document.getElementById('list');
  const q = document.getElementById('q');


  function buildTree(paths) {{
    const root = {{ dirs: {{}}, files: [] }};
    for (const p of paths) {{
      const parts = p.split('/');
      let node = root;
      for (let i = 0; i < parts.length; i++) {{
        const part = parts[i];
        const isFile = i === parts.length - 1;
        if (isFile) {{
          node.files.push({{ name: part, full: p }});
        }} else {{
          node.dirs[part] = node.dirs[part] || {{ dirs: {{}}, files: [] }};
          node = node.dirs[part];
        }}
      }}
    }}
    return root;
  }}

  // Crea enlaces respetando .md/.mdx con visor local
  function linkFor(org, repo, branch, fullPath) {{
   const fileParam =
    `/raw/${{encodeURIComponent(org)}}` +
    `/${{encodeURIComponent(repo)}}` +
    `/${{encodeURIComponent(branch)}}` +
    `/${{encodeURI(fullPath)}}`;
    if (/\\.(md|mdx)$/i.test(fullPath)) {{
      return `viewer.html?file=${{fileParam}}`;
    }}
    return `https://github.com/${{encodeURIComponent(org)}}/${{encodeURIComponent(repo)}}/blob/${{encodeURIComponent(branch)}}/${{encodeURI(fullPath)}}`;
  }}

  // Render recursivo (directorios expandibles)
  function renderNode(org, repo, branch, node, basePath, needle = '') {{
    const container = document.createElement('ul');
    container.className = 'tree';

    // Directorios
    const dirNames = Object.keys(node.dirs).sort();
    for (const d of dirNames) {{
      const path = basePath ? basePath + '/' + d : d;
      const sub = node.dirs[d];
      const subEl = renderNode(org, repo, branch, sub, path, needle);
      const hasChildren = subEl.childElementCount > 0;

      const dirMatches = !needle || d.toLowerCase().includes(needle) || hasChildren;
      if (!dirMatches) continue;

      const li = document.createElement('li');
      li.className = 'dir';

      const toggle = document.createElement('button');
      toggle.textContent = '▸';
      toggle.className = 'btn';
      toggle.setAttribute('aria-label','toggle');

      const label = document.createElement('span');
      label.textContent = d;
      label.style.fontWeight = '600';

      const header = document.createElement('div');
      header.className = 'header';
      header.appendChild(toggle);
      header.appendChild(label);

      const childrenWrap = document.createElement('div');
      childrenWrap.style.display = 'none';
      childrenWrap.appendChild(subEl);

      toggle.addEventListener('click', () => {{
        const open = childrenWrap.style.display !== 'none';
        childrenWrap.style.display = open ? 'none' : 'block';
        toggle.textContent = open ? '▸' : '▾';
      }});

      li.appendChild(header);
      li.appendChild(childrenWrap);
      container.appendChild(li);
    }}

    // Archivos
    for (const f of node.files.sort((a,b)=>a.name.localeCompare(b.name))) {{
      const show = !needle || f.name.toLowerCase().includes(needle) || f.full.toLowerCase().includes(needle);
      if (!show) continue;
      const li = document.createElement('li');
      li.className = 'file';
      const a = document.createElement('a');
      a.href = linkFor("{org}", repo, branch, f.full);
      a.target = '_blank';
      a.rel = 'noreferrer';
      a.textContent = f.name;
      li.appendChild(a);
      container.appendChild(li);
    }}
    return container;
  }}

  function render(filter = '') {{
    const needle = filter.trim().toLowerCase();
    listEl.innerHTML = '';

    for (const repo of Object.keys(tree).sort()) {{
      const entry = tree[repo] || {{}};
      const branch = entry.branch || 'main';
      const paths = entry.paths || [];

      const repoMatches = !needle || repo.toLowerCase().includes(needle);
      if (!repoMatches) continue;
      if (!paths.length) continue;

      const div = document.createElement('div');
      div.className = 'repo';
      div.innerHTML = `<h2>${{repo}}<span class="badge">${{branch}}</span></h2>`;


        const root = buildTree(paths);
        const treeEl = renderNode("{org}", repo, branch, root, '', '');
        div.appendChild(treeEl);


      listEl.appendChild(div);
    }}
  }}

  q.addEventListener('input', () => render(q.value));
  render();
}})();
</script>
</html>
"""

    VIEWER_HTML = r"""<!doctype html>
                     <html lang="es">
                     <head>
                       <meta charset="utf-8">
                       <title>Visor Markdown</title>
                       <meta name="viewport" content="width=device-width, initial-scale=1" />
                       <!-- Mermaid para bloques ```mermaid -->
                       <script src="https://unpkg.com/mermaid@10/dist/mermaid.min.js"></script>
                       <style>
                         body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,Apple Color Emoji,Noto Color Emoji;margin:2rem;line-height:1.6;background:#0b1020;color:#e5e7eb}
                         a{color:#8ab4f8}
                         pre,code{background:#0f172a;color:#e5e7eb;border-radius:6px}
                         pre{padding:1rem;overflow:auto}
                         code{padding:0.15rem 0.35rem}
                         h1,h2,h3,h4{margin-top:1.2em}
                         img{max-width:100%; height:auto}
                         table{border-collapse:collapse;width:100%;overflow:auto;display:block}
                         th,td{border:1px solid #334155;padding:6px}
                         .path{color:#9aa4b2;margin-bottom:1rem;word-break:break-all}
                         .error{color:#fca5a5}
                         .back {
                          display: inline-block;
                          background: #1e293b;
                          color: #8ab4f8;
                          border: 1px solid #243148;
                          border-radius: 8px;
                          padding: 0.5rem 1rem;
                          font-size: 0.95rem;
                          cursor: pointer;
                          transition: background 0.2s, transform 0.1s;
                        }
                        
                        .back:hover {
                          background: #2a3b54;
                          transform: translateY(-1px);
                        }
                        
                        .back:active {
                          transform: translateY(0);
                        }
                       </style>
                     </head>
                     <body>
                       <button class="back" onclick="window.location.href='index.html'">← Volver al índice</button>
                       <div class="path" id="mdpath"></div>
                       <article id="content">Cargando…</article>

                       <script>
                       const esc = s => s.replace(/[&<>"]/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

                       function md2html(md){
                         // 1) Mermaid: bloques ```mermaid ... ```
                         md = md.replace(/```mermaid\s*([\s\S]*?)```/g, (_,code)=>`<div class="mermaid">${code}</div>`);

                         // 2) Código normal con triple backticks
                         md = md.replace(/```([\s\S]*?)```/g, (_,code)=>`<pre><code>${esc(code)}</code></pre>`);

                         // Inline code
                         md = md.replace(/`([^`]+)`/g, (_,code)=>`<code>${esc(code)}</code>`);

                         // Cabeceras
                         md = md.replace(/^######\s?(.*)$/gm,'<h6>$1</h6>')
                                .replace(/^#####\s?(.*)$/gm,'<h5>$1</h5>')
                                .replace(/^####\s?(.*)$/gm,'<h4>$1</h4>')
                                .replace(/^###\s?(.*)$/gm,'<h3>$1</h3>')
                                .replace(/^##\s?(.*)$/gm,'<h2>$1</h2>')
                                .replace(/^#\s?(.*)$/gm,'<h1>$1</h1>');

                         // Listas
                         md = md.replace(/^\s*[-*+]\s+(.*)$/gm,'<li>$1</li>');
                         md = md.replace(/(<li>[\s\S]*?<\/li>)(?:(\n(?!<li>))+)/g, '<ul>$1</ul>\n');
                         md = md.replace(/^\s*\d+\.\s+(.*)$/gm,'<li>$1</li>');
                         md = md.replace(/(<li>[\s\S]*?<\/li>)(?:(\n(?!<li>))+)/g, m=> m.includes('<ul>')? m : '<ol>'+m+'</ol>\n');

                         // Énfasis
                         md = md.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
                                .replace(/\*([^*]+)\*/g,'<em>$1</em>')
                                .replace(/__([^_]+)__/g,'<strong>$1</strong>')
                                .replace(/_([^_]+)_/g,'<em>$1</em>');

                         // Imágenes y enlaces (sin resolver aún rutas relativas)
                         md = md.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_,alt,src)=>`<img alt="${esc(alt)}" src="${esc(src)}">`);
                         md = md.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_,text,href)=>`<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`);

                         // Tablas simples estilo GitHub
                         md = md.replace(/^(?:\|.+\|\n)+/gm, block=>{
                           const rows = block.trim().split('\n').map(r=>r.replace(/^\||\|$/g,'').split('|'));
                           const head = rows.shift(); if(!head) return block;
                           const sep = rows[0] && rows[0].every(c=>/^\s*:?-+:?\s*$/.test(c)) ? rows.shift() : null;
                           const thead = '<thead><tr>'+head.map(c=>`<th>${esc(c.trim())}</th>`).join('')+'</tr></thead>';
                           const tbody = '<tbody>'+rows.map(r=>'<tr>'+r.map(c=>`<td>${esc(c.trim())}</td>`).join('')+'</tr>').join('')+'</tbody>';
                           return `<table>${thead}${tbody}</table>`;
                         });

                         // Párrafos (evita envolver bloques ya HTML como pre/table/img/blockquote/div.mermaid)
                         md = md.split(/\n{2,}/).map(block=>{
                           const t = block.trim();
                           if (/^<(h\d|ul|ol|pre|table|img|blockquote|div\b)/i.test(t)) return block;
                           return '<p>'+block.replace(/\n/g,'<br>')+'</p>';
                         }).join('\n');

                         return md;
                       }

                       // Resuelve URLs relativas; si apuntan a carpeta, envía a README.md (fallback index.md)
                       function resolveRelativeUrls(container, basePath){
                         const baseDir = basePath.substring(0, basePath.lastIndexOf('/')+1);
                         const isHttp = u => /^(https?:)?\/\//i.test(u);
                         const hasExt = seg => /\.[a-z0-9]+$/i.test(seg);

                         const fixLink = (a)=>{
                           let href = a.getAttribute('href');
                           if(!href) return;

                           if (isHttp(href)) return;

                           href = href.replace(/^\.\//, '').replace(/\/{2,}/g,'/');

                           if (/\.mdx?$/i.test(href)) {
                             a.setAttribute('href', 'viewer.html?file=' +  baseDir  + encodeURI(href));
                             a.setAttribute('target','_self');
                             return;
                           }

                           const parts = href.split('/');
                           const last = parts.filter(Boolean).pop() || '';
                           const looksDir = href.endsWith('/') || !hasExt(last);

                           if (looksDir) {
                             const cand1 = baseDir + href.replace(/\/?$/,'/') + 'README.md';
                             const cand2 = baseDir + href.replace(/\/?$/,'/') + 'index.md';
                             a.setAttribute('href', 'viewer.html?file=' + cand1);
                             a.setAttribute('target','_self');
                             a.setAttribute('data-fallback', 'viewer.html?file=' + cand2);
                             return;
                           }

                           a.setAttribute('href', baseDir + href);
                           a.setAttribute('target','_blank');
                         };

                         container.querySelectorAll('img').forEach(img=>{
                           const src = img.getAttribute('src');
                           if(!src || /^(https?:)?\/\//i.test(src)) return;
                           img.setAttribute('src', baseDir + src.replace(/^\.\//,''));
                         });

                         container.querySelectorAll('a').forEach(a=>fixLink(a,'href'));
                       }

                       // Render
                       const params = new URLSearchParams(location.search);
                       let file = params.get('file');
                       document.getElementById('mdpath').textContent = file || '';

                       if (!file) {
    document.getElementById('content').innerHTML = '<p>No se indicó archivo (?file=...)</p>';
  } else {
    fetch(file)
      .then(r => {
        if (!r.ok) throw new Error('No se pudo cargar ' + file + ' (' + r.status + ')');
        return r.text();
      })
      .then(txt => {
        // console.log("Markdown descargado:", txt.slice(0,200));
        const html = md2html(txt);
        const content = document.getElementById('content');
        content.innerHTML = html;
        resolveRelativeUrls(content, file);

        if (window.mermaid) {
          try {
            mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' });
            mermaid.run({ querySelector: '.mermaid' });
          } catch (e) {
            console.error('Mermaid error:', e);
          }
        }
      })
      .catch(e => {
        const content = document.getElementById('content');
        content.innerHTML = '<p class="error">Error: ' + (e && e.message ? e.message : e) + '</p>';
      });
  }
                       </script>
                     </body>
                     </html>
"""

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(INDEX_HTML)
    with open(viewer_path, "w", encoding="utf-8") as f:
        f.write(VIEWER_HTML)


def run_fast_index(out_dir: str, org: str, months_back: int, paths: list[str], token: str | None, workers: int = 8):
    os.makedirs(out_dir, exist_ok=True)
    since = _months_ago_iso(months_back)
    repos = [r for r in _list_repos(org, token) if r.get("pushed_at", "") >= since]

    results: dict[str, dict] = {}

    def work(r):
        name = r.get("name")
        if not name:
            return name, {}
        branch = r.get("default_branch") or "main"
        try:
            files = _fetch_tree_paths(org, name, branch, token)
            filtered = [f for f in files if any(f == p or f.startswith(p + "/") for p in paths)]
            # agrupación legacy (no se usa para la UI nueva, pero se mantiene)
            groups: dict[str, list[str]] = {}
            for f in filtered:
                parts = f.split("/")
                if len(parts) >= 3:
                    key = "/".join(parts[:2])
                elif len(parts) == 2:
                    key = f
                else:
                    continue
                groups.setdefault(key, []).append(f)
            for k in list(groups.keys()):
                groups[k] = sorted(groups[k])
            # >>> NUEVO: añadimos paths planos ordenados (para árbol navegable)
            return name, {"branch": branch, "groups": groups, "paths": sorted(filtered)}
        except Exception:
            return name, {"branch": branch, "groups": {}, "paths": []}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, r) for r in repos]
        for fut in as_completed(futs):
            name, grouped = fut.result()
            if name:
                results[name] = grouped

    # Escribe tree.json e index/viewer
    tree_path = os.path.join(out_dir, "tree.json")
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    write_index_and_viewer(out_dir, org)

# ============================
# Tarea programada
# ============================

def scheduled_task():
    while True:
        print("[INFO] Ejecutando tarea de actualización… (FAST)")
        try:
            run_fast_index(out_dir=OUTPUT_DIR, org=ORG, months_back=MONTHS_BACK, paths=DEFAULT_PATHS, token=GITHUB_TOKEN_ENV, workers=MAX_WORKERS)
        except Exception as e:
            print(f"[ERROR] Falló la actualización: {e}")
        print(f"[INFO] Esperando {INTERVAL_HOURS} horas para la próxima ejecución…")
        time.sleep(INTERVAL_HOURS * 3600)

# ============================
# Rutas
# ============================
@app.get("/")
def home():
    tree_path = os.path.join(OUTPUT_DIR, "tree.json")
    if ADMIN_FIRST or not os.path.exists(tree_path) or os.path.getsize(tree_path) == 0:
        if request.args.get("skipadmin") != "1":
            return redirect(url_for("admin"))

    write_index_and_viewer(OUTPUT_DIR, ORG)
    return send_from_directory(OUTPUT_DIR, "index.html")


@app.get("/tree.json")
def tree():
    return send_from_directory(OUTPUT_DIR, "tree.json")


# Proxy RAW para ver .md e imágenes desde GitHub bajo mismo origen
@app.get("/raw/<org>/<repo>/<branch>/<path:subpath>")
def raw_proxy(org: str, repo: str, branch: str, subpath: str):
    url = f"https://raw.githubusercontent.com/{org}/{repo}/{branch}/{subpath}"
    try:
        req = urllib.request.Request(url)
        tok = os.getenv("GITHUB_TOKEN")
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            ctype = r.headers.get("Content-Type", "application/octet-stream")
            if subpath.lower().endswith((".md", ".mdx")):
                ctype = "text/markdown; charset=utf-8"
            return Response(data, headers={"Content-Type": ctype})
    except Exception as e:
        return Response(f"Error fetching raw: {e}", status=502)


# Admin
ADMIN_HTML = """
<!doctype html>
<html lang=es>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Admin — TractusX Docs</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;margin:2rem;background:#0b1020;color:#e5e7eb}
.card{padding:1rem;border:1px solid #243148;border-radius:12px;background:#12182c;max-width:720px}
label{display:block;margin:.5rem 0 .25rem}
input,button{background:#0b1020;border:1px solid #243148;border-radius:8px;padding:.5rem .75rem;color:#e5e7eb}
button{cursor:pointer}
.small{color:#a3a3a3}
</style>
<h1>Admin — Tractus-X Docs</h1>
<div class=card>
  <form method=post action="/run">
    <label>Token GitHub (opcional; no se guarda)</label>
    <input type=password name=token placeholder="ghp_…">
    {% if require_secret %}
    <label>Admin secret</label>
    <input type=password name=secret placeholder="secreto" required>
    {% endif %}
   <p style="margin-top:1rem;display:flex;gap:.5rem;align-items:center">
  <button type=submit style="flex:0 0 auto">Ejecutar ahora</button>
  <a href="/?skipadmin=1" target="_blank" 
     style="display:inline-block;padding:.5rem .75rem;border:1px solid #243148;
            border-radius:8px;background:#0b1020;color:#8ab4f8;
            text-decoration:none;text-align:center;flex:0 0 auto">
    Abrir índice
  </a>
</p>
  </form>
</div>
"""

@app.get("/admin")
def admin():
    return render_template_string(ADMIN_HTML, require_secret=bool(ADMIN_SECRET))

@app.post("/run")
def run_now():
    if ADMIN_SECRET:
        supplied = request.headers.get("X-Admin-Secret") or request.form.get("secret")
        if supplied != ADMIN_SECRET:
            abort(401)

    client_token = request.form.get("token") or request.headers.get("X-GitHub-Token") or GITHUB_TOKEN_ENV
    print(f"[INFO] Lanzando indexado manual (token={mask_token(client_token)})")

    try:
        run_fast_index(out_dir=OUTPUT_DIR, org=ORG, months_back=MONTHS_BACK, paths=DEFAULT_PATHS, token=client_token, workers=MAX_WORKERS)
    except Exception as e:
        return Response(f"Error ejecutando indexado: {e}", status=500)

    return redirect(url_for("home", skipadmin=1))

# Sirve cualquier otro archivo bajo OUT
@app.get("/<path:path>")
def any_file(path):
    return send_from_directory(OUTPUT_DIR, path)

# ============================
# Arranque
# ============================
if __name__ == "__main__":
    updater = threading.Thread(target=scheduled_task, daemon=True)
    updater.start()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
