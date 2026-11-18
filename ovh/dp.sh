# Data Platform depuis un terminal (OVHcloud Shell, Git Bash, CI) : jeton, export/import de configuration, lancement.
#
#   export DP_URL=https://<sous-domaine-du-projet>.eu.dataplatform.ovh.net
#   source ovh/dp.sh                    # demande la clé API et le secret (R3), garde le jeton dans la session
#   dp_exporter [dpe-config.tar]        # sauvegarde actions + workflows + environnements (DPE)
#   dp_importer dpe-config.tar          # crée / met à jour actions et workflows (ex. bac à sable d'un collègue)
#   dp_lancer_action <action_id>        # lance un job ; l'id est dans l'URL : .../dpe/#/action/<id>
#   dp_lancer_workflow <workflow_id>    # idem pour un workflow : .../dpe/#/workflow/<id>
#
# Endpoints (docs.dataplatform.ovh.net, llms-full lu le 2026-11-18) :
#   POST /iam/login {"auth_mode": "apikey", ...}           -> token          (developers-api-authentication)
#   GET  /dpe/v3/configuration/export, POST .../import     Authorization: Bearer (tutorials-export-import-config)
#   POST /dpe/v3/actions/<id>/start?app_id=...&type=cam&token=...           (lancement d'action, doc « Launching
#        Actions and Workflows ») ; /dpe/v3/workflows/<id>/start est DÉDUIT par analogie (non écrit dans la doc).
# Le jeton est court (durée réglée dans l'IAM) : relancer dp_login s'il expire. Rien n'est écrit sur disque.

: "${DP_URL:?définir DP_URL=https://<sous-domaine>.eu.dataplatform.ovh.net}"
DP_APP_LANCEMENT="55c1423560702d6426490f38"   # app_id des exemples officiels de lancement

dp_login() {
    local cle secret reponse
    read -rp "Clé API (R3) : " cle; read -rsp "Secret (R3) : " secret; echo
    # Corps lu sur l'entrée standard : le secret n'apparaît pas dans la liste des processus
    reponse=$(curl -fsS -X POST "$DP_URL/iam/login" -H 'Content-Type: application/json' --data @- <<FIN
{"auth_mode": "apikey", "apikey": "$cle", "secretkey": "$secret", "app_id": "forepaas"}
FIN
) || { echo "échec de connexion (clés, ou DP_URL)"; return 1; }
    unset cle secret
    DP_TOKEN=$(printf '%s' "$reponse" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    [ -n "$DP_TOKEN" ] && echo "connecté (jeton en mémoire)" || { echo "pas de jeton dans la réponse"; return 1; }
}

dp_exporter() {
    local sortie="${1:-dpe-config-$(date +%Y%m%d-%H%M).tar}"
    curl -fsS "$DP_URL/dpe/v3/configuration/export" -H "Authorization: Bearer $DP_TOKEN" -o "$sortie" \
        && echo "exporté : $sortie" && tar -tf "$sortie" | head -40
}

dp_importer() {
    [ -f "$1" ] || { echo "usage : dp_importer <archive.tar>"; return 1; }
    curl -fsS -X POST "$DP_URL/dpe/v3/configuration/import?response=true" \
        -H "Authorization: Bearer $DP_TOKEN" --form "archive=@$1" && echo && echo "importé : $1"
}

_dp_lancer() {
    curl -sS -w '\nHTTP %{http_code}\n' -X POST \
        "$DP_URL/dpe/v3/$1/$2/start?app_id=$DP_APP_LANCEMENT&type=cam&token=$DP_TOKEN" \
        -H 'content-type: application/json' --data '[]'
}
dp_lancer_action()   { _dp_lancer actions "${1:?usage : dp_lancer_action ID}"; }
dp_lancer_workflow() { _dp_lancer workflows "${1:?usage : dp_lancer_workflow ID}"; }

dp_login
