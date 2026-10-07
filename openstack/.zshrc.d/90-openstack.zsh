alias os='openstack'

# Prints the cloud names defined in ./clouds.yaml, one per line. Only the
# direct children of the top-level `clouds:` key count; their indent is taken
# from the first one, so nested keys (auth, region_name, ...) are skipped.
_os_cloud_names() {
  [[ -r clouds.yaml ]] || return 1
  awk -v q="'" '
    /^clouds:[[:space:]]*(#.*)?$/ { inside = 1; next }
    !inside || /^[[:space:]]*(#|$)/ { next }
    /^[^[:space:]]/ { exit }
    {
      match($0, /^[[:space:]]+/)
      if (!depth) depth = RLENGTH
      if (RLENGTH != depth) next
      key = substr($0, depth + 1)
      sub(/[[:space:]]*:.*/, "", key)
      gsub("^[\"" q "]|[\"" q "]$", "", key)
      print key
    }
  ' clouds.yaml
}

# os-cloud         print the active cloud
# os-cloud NAME    export OS_CLOUD=NAME, NAME must be in ./clouds.yaml
# os-cloud -       unset OS_CLOUD
os-cloud() {
  if (( ! $# )); then
    print -r -- "${OS_CLOUD:-<none>}"
    return
  fi
  if [[ $1 == - ]]; then
    unset OS_CLOUD
    return
  fi

  local -a clouds
  clouds=(${(f)"$(_os_cloud_names)"})
  if (( ! ${clouds[(Ie)$1]} )); then
    print -ru2 -- "os-cloud: no cloud '$1' in ${PWD%/}/clouds.yaml"
    return 1
  fi
  export OS_CLOUD=$1
}

_os-cloud() {
  local -a clouds
  clouds=(${(f)"$(_os_cloud_names)"})
  _describe -t clouds 'cloud' clouds
}

compdef _os-cloud os-cloud

# flush all openstack envvars
function openstack_flush() {
  unset -m 'OS_*' || true
}

