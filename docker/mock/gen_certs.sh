#!/usr/bin/env bash
# Throwaway CA + server certificate for the mock receiver's HTTPS listener.
# Generated per CI run, never committed (docker/mock/certs/ is gitignored).
set -euo pipefail
d="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$d"
cd "$d"
# Python 3.13 verifies with VERIFY_X509_STRICT: the CA needs keyUsage and the
# leaf needs key identifiers.
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=viz-alert-snapshot CI CA" \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" -keyout ca.key -out ca.pem 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=api.telegram.org" \
  -keyout server.key -out server.csr 2>/dev/null
printf 'subjectAltName=DNS:api.telegram.org,DNS:slack.com\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\nbasicConstraints=critical,CA:FALSE\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' > ext.cnf
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 2 \
  -extfile ext.cnf -out server.pem 2>/dev/null
chmod 644 ./*.pem ./*.key
echo "certs in $d"
