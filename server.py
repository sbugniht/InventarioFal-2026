import os
import sys
import socket
import asyncio
import datetime
import ipaddress
import contextlib
import shutil
import sqlite3

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Route

import api
import db
import trascrizione
from config import CONFIG

# --- CONFIGURAZIONE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = "0.0.0.0"  # raggiungibile da tutta la rete locale
PORT = CONFIG["porta"]  # unica porta pubblica: accetta sia https:// (l'app) sia http:// (pagina certificato)
PORT_HTTPS_INTERNO = 8443  # solo su 127.0.0.1, raggiunte tramite lo smistatore
PORT_HTTP_INTERNO = 8001
CERT_DIR = os.path.join(BASE_DIR, "certs")


# --- Manutenzione: backup del database e cancellazione delle trascrizioni vecchie ---
def backup_database():
    cartella = CONFIG.get("backup_cartella")
    if not cartella:
        return  # backup non ancora configurato (cartella del NAS in config.json)
    os.makedirs(cartella, exist_ok=True)
    destinazione = os.path.join(cartella, f"inventario-{datetime.datetime.now():%Y%m%d-%H%M}.db")
    with sqlite3.connect(destinazione) as copia:
        db.connessione().backup(copia)  # copia coerente anche mentre si scrive
    limite = datetime.datetime.now() - datetime.timedelta(days=CONFIG.get("backup_giorni", 30))
    for nome in os.listdir(cartella):
        percorso = os.path.join(cartella, nome)
        if nome.startswith("inventario-") and nome.endswith(".db") and \
                datetime.datetime.fromtimestamp(os.path.getmtime(percorso)) < limite:
            os.remove(percorso)
    print(f"[💾] Backup: {destinazione}", flush=True)


def cancella_trascrizioni_vecchie():
    """Le trascrizioni servono solo per controllare l'inventario: dopo N giorni dalla chiusura si cancellano."""
    limite = (datetime.datetime.now() - datetime.timedelta(days=CONFIG.get("trascrizioni_giorni", 90))) \
        .isoformat(timespec="seconds")
    db.esegui("UPDATE righe SET trascrizione = NULL WHERE trascrizione IS NOT NULL AND inventario_id IN "
              "(SELECT id FROM inventari WHERE chiuso_il < ?)", (limite,))


async def manutenzione():
    while True:
        for compito in (backup_database, cancella_trascrizioni_vecchie):
            try:
                await asyncio.to_thread(compito)
            except Exception as e:
                print(f"[⚠️] {compito.__name__}: {e}", flush=True)
        await asyncio.sleep(CONFIG.get("backup_minuti", 60) * 60)


@contextlib.asynccontextmanager
async def lifespan(app):
    # Carica Whisper all'avvio, così la prima trascrizione è veloce
    # (poi si scarica da solo se resta inattivo, vedi trascrizione.py)
    compiti = [asyncio.create_task(asyncio.to_thread(trascrizione.precarica)),
               asyncio.create_task(manutenzione())]
    yield
    for compito in compiti:
        compito.cancel()


app = Starlette(routes=api.ROUTES, lifespan=lifespan)

def ip_locali() -> list[str]:
    """IPv4 di rete locale di questa macchina (Wi-Fi ed Ethernet), su macOS e Windows."""
    ips = []
    with contextlib.suppress(OSError):
        # Trucco UDP: nessun pacchetto parte, ma il sistema sceglie l'interfaccia di uscita
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    unici = []
    for ip in ips:
        indirizzo = ipaddress.ip_address(ip)
        if indirizzo.is_private and not indirizzo.is_loopback and not indirizzo.is_link_local and ip not in unici:
            unici.append(ip)
    return unici or ["127.0.0.1"]


def _salva_chiave(chiave, percorso: str):
    with open(percorso, "wb") as f:
        f.write(chiave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                     serialization.NoEncryption()))
    with contextlib.suppress(OSError):
        os.chmod(percorso, 0o600)


def prepara_certificati(ips: list[str]) -> tuple[str, str]:
    """HTTPS con una piccola autorità di certificazione (CA) locale.
    I browser concedono il microfono solo su HTTPS; installando una volta la CA su ogni
    dispositivo, il sito diventa attendibile senza avvisi. La CA è limitata (nameConstraints)
    agli indirizzi di rete locale: non può certificare siti reali di Internet.
    Il certificato del server viene rigenerato se gli IP della macchina cambiano.
    Usa la libreria cryptography: non serve openssl installato (Windows)."""
    os.makedirs(CERT_DIR, exist_ok=True)
    ca_key, ca_cert = os.path.join(CERT_DIR, "ca-key.pem"), os.path.join(CERT_DIR, "ca.pem")
    cert, chiave = os.path.join(CERT_DIR, "server.pem"), os.path.join(CERT_DIR, "server-key.pem")
    file_ip = os.path.join(CERT_DIR, "ip.txt")
    host_locale = socket.gethostname().removesuffix(".local") + ".local"
    firma = ",".join(ips + [host_locale])
    adesso = datetime.datetime.now(datetime.timezone.utc)

    if not os.path.exists(ca_cert):
        print("[🔐] Creo l'autorità di certificazione locale...")
        chiave_ca = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome_ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Assistente Vocale - CA locale")])
        reti_locali = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"]
        certificato_ca = (
            x509.CertificateBuilder()
            .subject_name(nome_ca).issuer_name(nome_ca)
            .public_key(chiave_ca.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(adesso).not_valid_after(adesso + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(chiave_ca.public_key()), critical=False)
            .add_extension(x509.NameConstraints(
                permitted_subtrees=[x509.IPAddress(ipaddress.ip_network(r)) for r in reti_locali]
                + [x509.DNSName("local"), x509.DNSName("localhost")],
                excluded_subtrees=None), critical=True)
            .sign(chiave_ca, hashes.SHA256())
        )
        _salva_chiave(chiave_ca, ca_key)
        with open(ca_cert, "wb") as f:
            f.write(certificato_ca.public_bytes(serialization.Encoding.PEM))

    if os.path.exists(cert) and os.path.exists(file_ip) and open(file_ip).read() == firma:
        return cert, chiave

    print(f"[🔐] Genero il certificato del server per {', '.join(ips)}...")
    with open(ca_key, "rb") as f:
        chiave_ca = serialization.load_pem_private_key(f.read(), password=None)
    with open(ca_cert, "rb") as f:
        certificato_ca = x509.load_pem_x509_certificate(f.read())
    chiave_server = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san = [x509.IPAddress(ipaddress.ip_address(ip)) for ip in dict.fromkeys(ips + ["127.0.0.1"])]
    san += [x509.DNSName("localhost"), x509.DNSName(host_locale)]
    # Requisiti iOS/macOS: durata <= 825 giorni, serverAuth, SAN
    certificato = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Assistente Vocale")]))
        .issuer_name(certificato_ca.subject)
        .public_key(chiave_server.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(adesso).not_valid_after(adesso + datetime.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(chiave_ca, hashes.SHA256())
    )
    _salva_chiave(chiave_server, chiave)
    with open(cert, "wb") as f:
        f.write(certificato.public_bytes(serialization.Encoding.PEM))
    with open(file_ip, "w") as f:
        f.write(firma)
    return cert, chiave


def abbassa_priorita():
    """Il server lascia sempre la precedenza ad AutoCAD, SketchUp, Excel."""
    if not CONFIG["priorita_bassa"]:
        return
    try:
        if sys.platform == "win32":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x4000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                    BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception as e:
        print(f"[⚠️] Impossibile abbassare la priorità: {e}")


# --- Ingresso HTTP: rimanda all'app se il certificato è già installato, altrimenti spiega come installarlo ---
async def pagina_ca(request):
    return FileResponse(os.path.join(BASE_DIR, "static", "certificato.html"))


async def scarica_ca(request):
    return FileResponse(
        os.path.join(CERT_DIR, "ca.pem"),
        media_type="application/x-x509-ca-cert",
        filename="AssistenteVocale-CA.crt",
    )


app_ca = Starlette(routes=[Route("/", pagina_ca), Route("/ca.crt", scarica_ca)])


async def _travasa(reader, writer):
    try:
        while dati := await reader.read(65536):
            writer.write(dati)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def smista_connessione(reader, writer):
    """Guarda il primo byte: 0x16 è l'inizio di un handshake TLS (https), altrimenti è http.
    Così l'indirizzo funziona qualunque protocollo scelga il browser."""
    client = writer.get_extra_info("peername")[0]
    try:
        primo = await asyncio.wait_for(reader.read(1), timeout=10)
    except asyncio.TimeoutError:
        primo = b""
    if not primo:
        writer.close()
        return
    https = primo == b"\x16"
    print(f"[🌐] Connessione da {client} ({'https' if https else 'http'})", flush=True)
    try:
        r2, w2 = await asyncio.open_connection(
            "127.0.0.1", PORT_HTTPS_INTERNO if https else PORT_HTTP_INTERNO)
    except OSError:
        writer.close()
        return
    w2.write(primo)
    await asyncio.gather(_travasa(reader, w2), _travasa(r2, writer))


async def avvia(cert: str, chiave: str):
    server_https = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=PORT_HTTPS_INTERNO, ssl_certfile=cert, ssl_keyfile=chiave,
        access_log=False))
    server_ca = uvicorn.Server(uvicorn.Config(
        app_ca, host="127.0.0.1", port=PORT_HTTP_INTERNO, access_log=False))
    smistatore = await asyncio.start_server(smista_connessione, HOST, PORT)
    async with smistatore:
        await asyncio.gather(server_https.serve(), server_ca.serve(), smistatore.serve_forever())


if __name__ == "__main__":
    abbassa_priorita()
    for messaggio in db.inizializza():
        print(messaggio)
    ips = ip_locali()
    cert, chiave = prepara_certificati(ips)
    print(f"\n🎙️ Whisper: {CONFIG['whisper_modello']} ({trascrizione.BACKEND}) · LLM: "
          f"{CONFIG['llm_modello'] if CONFIG['llm_attivo'] else 'disattivato'}")
    print(f"🌐 Su questo computer:  https://localhost:{PORT}")
    for ip in ips:
        print(f"🌐 Dalla rete locale:   https://{ip}:{PORT}")
    print(f"🔐 Nuovo dispositivo? Apri http://{ips[0]}:{PORT} per installare il certificato\n")
    asyncio.run(avvia(cert, chiave))
