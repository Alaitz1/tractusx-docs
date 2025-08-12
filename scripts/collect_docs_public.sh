#!/usr/bin/env bash
set -euo pipefail

# Parámetros
ORG="${ORG:-eclipse-tractusx}"
MONTHS_BACK="${MONTHS_BACK:-6}"
OUT="${OUT:-tractusx-docs}"
LOG="${LOG:-tractusx-docs.log}"
PATHS=("docs" "documentation" "doc" "website/docs")

# Requisitos
for cmd in curl jq git rsync python3; do
  command -v "$cmd" >/dev/null || { echo "Falta $cmd"; exit 1; }
done

# Calcula fecha de corte
SINCE="$(python3 - <<PY
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
print((datetime.now(timezone.utc) - relativedelta(months=int("$MONTHS_BACK"))).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"

echo "==> Org: $ORG"
echo "==> Repos con cambios desde: $SINCE"
echo "==> Salida: $OUT"
mkdir -p "$OUT"
: > "$LOG"

fetch_page () {
  local page="$1"
  curl -s "https://api.github.com/orgs/$ORG/repos?per_page=100&page=$page&type=public"
}
AUTH_HEADER=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer $GITHUB_TOKEN")
fi

page=1
updated_count=0
while : ; do
  JSON="$(fetch_page "$page")"
  LEN="$(echo "$JSON" | jq 'length')"
  [[ "$LEN" -eq 0 ]] && break

  echo "$JSON" | jq -r --arg SINCE "$SINCE" '
    .[]
    | select(.pushed_at >= $SINCE)
    | [.name, .default_branch, .pushed_at]
    | @tsv
  ' | while IFS=$'\t' read -r REPO DEFAULT_BRANCH PUSHED; do
      DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
      echo ">>> $REPO (último push: $PUSHED) [rama: $DEFAULT_BRANCH]" | tee -a "$LOG"
      updated_count=$((updated_count+1))

      EXISTING=()
      for P in "${PATHS[@]}"; do
        CODE="$(curl -s -o /dev/null -w "%{http_code}" \
          "https://api.github.com/repos/$ORG/$REPO/contents/$P?ref=$DEFAULT_BRANCH")"
        [[ "$CODE" == "200" ]] && EXISTING+=("$P")
      done

      if [[ ${#EXISTING[@]} -eq 0 ]]; then
        echo "    -> no hay rutas de documentación" | tee -a "$LOG"
        continue
      fi

      echo "    -> encontrado(s): ${EXISTING[*]} (descargando…)" | tee -a "$LOG"
      TMPDIR="$(mktemp -d)"
      git -C "$TMPDIR" init -q
      git -C "$TMPDIR" remote add origin "https://github.com/$ORG/$REPO.git"
      if git -C "$TMPDIR" fetch -q --depth=1 origin "$DEFAULT_BRANCH"; then
        git -C "$TMPDIR" sparse-checkout init --cone
        git -C "$TMPDIR" sparse-checkout set "${EXISTING[@]}"
        git -C "$TMPDIR" checkout -q "$DEFAULT_BRANCH"

        for P in "${EXISTING[@]}"; do
          if [[ -d "$TMPDIR/$P" ]]; then
            mkdir -p "$OUT/$REPO/$P"
            rsync -a "$TMPDIR/$P/" "$OUT/$REPO/$P/"
            echo "        -> copiado en $OUT/$REPO/$P/" | tee -a "$LOG"
          fi
        done
      else
        echo "    -> fetch falló" | tee -a "$LOG"
      fi
      rm -rf "$TMPDIR"
    done

  page=$((page+1))
done

echo "==> Repos actualizados en el rango: $updated_count" | tee -a "$LOG"

# Generar índice HTML + tree.json
echo "==> Generando índice HTML..."
TREE_JSON="$OUT/tree.json"
echo "{}" | jq '.' > "$TREE_JSON"

for REPO_DIR in "$OUT"/*; do
  [[ -d "$REPO_DIR" ]] || continue
  FILES_ALL=()
  for P in "${PATHS[@]}"; do
    [[ -d "$REPO_DIR/$P" ]] || continue
    while IFS= read -r f; do
      FILES_ALL+=("$P/${f#./}")
    done < <(cd "$REPO_DIR/$P" && find . -type f -print | sed 's#^\./##')
  done
  REPO_NAME=$(basename "$REPO_DIR")
  printf '%s\n' "${FILES_ALL[@]}" | jq -R . | jq -s . > /tmp/files_"$REPO_NAME".json
  TMP=$(mktemp)
  jq --arg repo "$REPO_NAME" --slurpfile files /tmp/files_"$REPO_NAME".json \
     '. + {($repo): $files[0]}' "$TREE_JSON" > "$TMP" && mv "$TMP" "$TREE_JSON"
  rm -f /tmp/files_"$REPO_NAME".json
done

INDEX="$OUT/index.html"
cat > "$INDEX" <<'HTML'
<!doctype html>
<html lang="es">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Índice de documentación — Eclipse Tractus-X</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;margin:2rem;background:#0b1020;color:#e5e7eb}
h1{margin-bottom:1rem}
.repo{margin:0 0 1.25rem;padding:1rem;border:1px solid #243148;border-radius:12px;background:#12182c}
a{color:#8ab4f8;text-decoration:none}a:hover{text-decoration:underline}
ul{margin:0.25rem 0 0.75rem 1.25rem}
small{color:#a3a3a3}
</style>
<h1>Índice de documentación — Eclipse Tractus-X</h1>
<p><small>Generado localmente. Haz clic para abrir los ficheros.</small></p>
<div id="list"></div>
<script>
(async () => {
  const res = await fetch('tree.json');
  const tree = await res.json();
  const listEl = document.getElementById('list');
  for (const repo of Object.keys(tree).sort()) {
    const files = tree[repo] || [];
    const div = document.createElement('div');
    div.className = 'repo';
    div.innerHTML = `<h2>${repo}</h2>`;
    if (!files.length) {
      div.innerHTML += '<p><em>Sin archivos en rutas de documentación</em></p>';
    } else {
      const ul = document.createElement('ul');
      files.forEach(f => {
        li = document.createElement('li');
        li.innerHTML = `<a href="${encodeURI(repo)}/${encodeURI(f)}" target="_blank">${f}</a>`;
        ul.appendChild(li);
      });
      div.appendChild(ul);
    }
    listEl.appendChild(div);
  }
})();
</script>
</html>
HTML

echo "==> Listo."
echo "Abre en el navegador:"
echo "   $(cd "$OUT"; pwd)/index.html"
echo "Log:"
echo "   $(pwd)/$LOG"
