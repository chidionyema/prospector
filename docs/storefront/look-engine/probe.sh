#!/bin/bash
# @ledger network | ./probe.sh | Searches the Met collection API by hand, to choose accession numbers rather than guess search terms.
met_probe () {
  echo "--- $1  [$2]"
  ids=$(curl -s "https://collectionapi.metmuseum.org/public/collection/v1/search?isPublicDomain=true&hasImages=true&q=$(printf %s "$2" | sed 's/ /%20/g')" | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(str(x) for x in (d.get('objectIDs') or [])[:6]))")
  for id in $ids; do
    curl -s "https://collectionapi.metmuseum.org/public/collection/v1/objects/$id" | python3 -c "
import sys,json
o=json.load(sys.stdin)
if o.get('isPublicDomain') and o.get('primaryImageSmall'):
    print('   %-7s %-50s | %-14s | %s' % (o['objectID'], o['title'][:50], (o.get('objectDate') or '')[:14], o.get('classification') or ''))
"
  done
}
met_probe NR "speaking trumpet"
met_probe NR2 "phonograph"
met_probe NR3 "tuning"
met_probe RD "slide rule"
met_probe RD2 "arithmetic"
met_probe RD3 "account book"
met_probe HERO "sieve"
met_probe HERO2 "assay"
