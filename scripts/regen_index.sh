#!/usr/bin/env bash
set -euo pipefail

# Ejecuta este script dentro de ~/tractusx-docs
ROOT="."                             # carpeta actual
TREE_JSON="$ROOT/tree.json"
INDEX_HTML="$ROOT/index.html"
VIEWER_HTML="$ROOT/viewer.html"

# Rutas típicas donde guardaste docs (no se muestran como grupos; solo para buscar)
SEARCH_PATHS=("docs" "documentation" "doc" "website/docs" "architecture" "developer")

echo "==> Generando tree.json desde $(pwd)"
echo "{}" | jq '.' > "$TREE_JSON"

# Repos = subcarpetas directas
for REPO_DIR in "$ROOT"/*; do
  [[ -d "$REPO_DIR" ]] || continue
  REPO_NAME="$(basename "$REPO_DIR")"
  [[ "$REPO_NAME" == "tree.json" || "$REPO_NAME" == "index.html" || "$REPO_NAME" == "viewer.html" ]] && continue

  # Reunir archivos manteniendo rutas relativas tal cual están bajo el repo
  mapfile -t FILES < <(
    for P in "${SEARCH_PATHS[@]}"; do
      if [[ -d "$REPO_DIR/$P" ]]; then
        (cd "$REPO_DIR" && find "$P" -type f -print)
      fi
    done
  )

  if [[ ${#FILES[@]} -gt 0 ]]; then
    # Orden determinista
    IFS=$'\n' read -r -d '' -a FILES_SORTED < <(printf '%s\0' "${FILES[@]}" | sort -z | xargs -0 -n1 printf '%s\n' && printf '\0')
    printf '%s\n' "${FILES_SORTED[@]}" | jq -R . | jq -s . > "/tmp/files_${REPO_NAME}.json"
    TMP=$(mktemp)
    jq --arg repo "$REPO_NAME" --slurpfile f "/tmp/files_${REPO_NAME}.json" \
       '. + {($repo): $f[0]}' "$TREE_JSON" > "$TMP" && mv "$TMP" "$TREE_JSON"
    rm -f "/tmp/files_${REPO_NAME}.json"
    echo "   ✓ $REPO_NAME: ${#FILES_SORTED[@]} ficheros indexados"
  else
    TMP=$(mktemp)
    jq --arg repo "$REPO_NAME" '. + {($repo): []}' "$TREE_JSON" > "$TMP" && mv "$TMP" "$TREE_JSON"
    echo "   - $REPO_NAME: sin ficheros en ${SEARCH_PATHS[*]}"
  fi
done
# ---------- viewer.html (renderiza Markdown sin internet) ----------
# Mini renderizador Markdown (soporta títulos, énfasis, código, listas, tablas sencillas, links e imágenes)
cat > "$VIEWER_HTML" <<'HTML'
<!doctype html>
<html lang="es">
<meta charset="utf-8">
<title>Visor Markdown</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,Apple Color Emoji,Noto Color Emoji;margin:2rem;line-height:1.6;background:#0b1020;color:#e5e7eb}
  a{color:#8ab4f8} pre,code{background:#0f172a;color:#e5e7eb;border-radius:6px}
  pre{padding:1rem;overflow:auto} code{padding:0.15rem 0.35rem}
  h1,h2,h3,h4{margin-top:1.2em}
  img{max-width:100%; height:auto}
  table{border-collapse:collapse;width:100%;overflow:auto;display:block}
  th,td{border:1px solid #334155;padding:6px}
  .path{color:#9aa4b2;margin-bottom:1rem}
</style>
<div class="path" id="mdpath"></div>
<article id="content">Cargando…</article>
<script>
// Utilidad: escapar HTML
const esc = s => s.replace(/[&<>"]/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// Render simple de Markdown (no perfecto, pero suficiente offline)
function md2html(md){
  // Bloques de código triple
  md = md.replace(/```([\s\S]*?)```/g, (_,code)=>`<pre><code>${esc(code)}</code></pre>`);
  // Inline code
  md = md.replace(/`([^`]+)`/g, (_,code)=>`<code>${esc(code)}</code>`);
  // Encabezados
  md = md.replace(/^######\s?(.*)$/gm,'<h6>$1</h6>')
         .replace(/^#####\s?(.*)$/gm,'<h5>$1</h5>')
         .replace(/^####\s?(.*)$/gm,'<h4>$1</h4>')
         .replace(/^###\s?(.*)$/gm,'<h3>$1</h3>')
         .replace(/^##\s?(.*)$/gm,'<h2>$1</h2>')
         .replace(/^#\s?(.*)$/gm,'<h1>$1</h1>');
  // Listas ordenadas y no ordenadas (básico)
  md = md.replace(/^\s*[-*+]\s+(.*)$/gm,'<li>$1</li>');
  md = md.replace(/(<li>[\s\S]*?<\/li>)(?:(\n(?!<li>))+)/g, '<ul>$1</ul>\n');
  md = md.replace(/^\s*\d+\.\s+(.*)$/gm,'<li>$1</li>');
  md = md.replace(/(<li>[\s\S]*?<\/li>)(?:(\n(?!<li>))+)/g, m=> m.includes('<ul>')? m : '<ol>'+m+'</ol>\n');
  // Negrita / cursiva
  md = md.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
         .replace(/\*([^*]+)\*/g,'<em>$1</em>')
         .replace(/__([^_]+)__/g,'<strong>$1</strong>')
         .replace(/_([^_]+)_/g,'<em>$1</em>');
  // Imágenes ![alt](src)
  md = md.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_,alt,src)=>`<img alt="${esc(alt)}" src="${esc(src)}">`);
  // Enlaces [text](href)
  md = md.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_,text,href)=>`<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`);
  // Tablas simples: líneas con |  (muy básico)
  md = md.replace(/^(?:\|.+\|\n)+/gm, block=>{
    const rows = block.trim().split('\n').map(r=>r.replace(/^\||\|$/g,'').split('|'));
    const head = rows.shift(); if(!head) return block;
    const sep = rows[0] && rows[0].every(c=>/^\s*:?-+:?\s*$/.test(c)) ? rows.shift() : null;
    const thead = '<thead><tr>'+head.map(c=>`<th>${esc(c.trim())}</th>`).join('')+'</tr></thead>';
    const tbody = '<tbody>'+rows.map(r=>'<tr>'+r.map(c=>`<td>${esc(c.trim())}</td>`).join('')+'</tr>').join('')+'</tbody>';
    return `<table>${thead}${tbody}</table>`;
  });
  // Párrafos (simple): líneas no HTML agrupadas
  md = md.split(/\n{2,}/).map(block=>{
    if (/^\s*<(h\d|ul|ol|pre|table|img|blockquote)/i.test(block.trim())) return block;
    return '<p>'+block.replace(/\n/g,'<br>')+'</p>';
  }).join('\n');
  return md;
}

// Resolver rutas relativas de imágenes y enlaces al mismo repo
function resolveRelativeUrls(container, basePath){
  const fix = (el, attr)=>{
    const u = el.getAttribute(attr); if(!u) return;
    if (/^(https?:)?\/\//i.test(u)) return; // absoluto
    // Construye ruta relativa al archivo md
    const baseDir = basePath.substring(0, basePath.lastIndexOf('/')+1);
    el.setAttribute(attr, baseDir + u);
  };
  container.querySelectorAll('img').forEach(img=>fix(img,'src'));
  container.querySelectorAll('a').forEach(a=>{
    const href = a.getAttribute('href'); if (!href) return;
    if (/^(https?:)?\/\//i.test(href)) return;
    // si apunta a otro .md local, abrir en el visor
    if (/\.mdx?$/i.test(href)) {
      const baseDir = basePath.substring(0, basePath.lastIndexOf('/')+1);
      a.setAttribute('href', 'viewer.html?file=' + encodeURIComponent(baseDir + href));
      a.setAttribute('target','_self');
    } else {
      const baseDir = basePath.substring(0, basePath.lastIndexOf('/')+1);
      a.setAttribute('href', baseDir + href);
      a.setAttribute('target','_blank');
    }
  });
}

const params = new URLSearchParams(location.search);
const file = params.get('file'); // ej: repo/path/to/file.md
document.getElementById('mdpath').textContent = file || '';

if (!file) {
  document.getElementById('content').innerHTML = '<p>No se indicó archivo (?file=...)</p>';
} else {
  fetch(file).then(r=>{
    if(!r.ok) throw new Error('No se pudo cargar '+file);
    return r.text();
  }).then(txt=>{
    const html = md2html(txt);
    const content = document.getElementById('content');
    content.innerHTML = html;
    resolveRelativeUrls(content, file);
  }).catch(e=>{
    document.getElementById('content').innerHTML = '<p>Error: '+e.message+'</p>';
  });
}
</script>
</html>
HTML

echo "==> Generado:"
echo "   $(pwd)/tree.json"
echo "   $(pwd)/index.html"
echo "   $(pwd)/viewer.html"
echo "Abre index.html con:  python3 -m http.server 8000"
