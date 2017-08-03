rem "D:\PUBLICSYSTEM\Program Files (x86)\OpenSSL\bin\openssl.exe" x509 -outform der -in %1 -out %1.crt
openssl pkcs12 -inkey client.pem.key -in client.pem.crt -export -out client.pfx
openssl crl2pkcs7 -nocrl -certfile server.pem.crt -out server.p7b
pause
