# Progetto: "scrcpy per iOS" (cattura video + controllo input)

## Obiettivo

Software unico che:

1. Cattura il feed video di un iPhone collegato al PC.
2. Permette di controllarlo da PC (click, drag, scroll, tastiera) tramite **backend di input intercambiabili**:
   - **ESP32** che simula un mouse Bluetooth LE HID (funziona senza jailbreak).
   - **Jailbreak** con touch injection on-device (coordinate assolute, multitouch), se disponibile.
3. All'avvio rileva automaticamente cosa è disponibile e sceglie il backend, con override manuale.

Contesto: l'utente ha un iPhone con jailbreak disponibile. Uso previsto: lavoro di mobile security / testing.

---

## Fatti tecnici emersi (base di partenza)

### Alternative esistenti a scrcpy su iOS

Non esiste nulla di comodo quanto scrcpy. Opzioni note:

- **QuickTime (macOS)**: mirroring via USB, solo video, nessun input.
- **UxPlay / RPiPlay**: ricevitore AirPlay open source, wireless, solo audio/video, fps alti.
- **pymobiledevice3 / go-ios / tidevice**: screenshot e streaming via DVT/screenshotr; con **WebDriverAgent** anche tap e swipe (richiede developer provisioning).
- **Con jailbreak**: Veency (VNC, solo versioni vecchie/rootful), oppure tweak/daemon con touch injection via IOHID. Frida/objection non fanno mirroring ma sono utili per il pentest.

### Mouse esterno su iPhone

- Supportato tramite **AssistiveTouch** (iOS 13+): Impostazioni → Accessibilità → Tocco → AssistiveTouch.
- Bluetooth oppure USB (con adattatore).
- Il cursore è un cerchio, non una freccia. Click sinistro = tap, rotella = scroll, nessun hover.
- Gli swipe da bordo (Home, Centro di Controllo) richiedono il menu AssistiveTouch o gesti personalizzati assegnati ai tasti del mouse.
- Il mouse è **relativo**: iOS non ha puntatore con coordinate assolute, e applica accelerazione al puntatore.

### Vincolo USB

Con l'iPhone collegato al PC per il video, l'iPhone è un *device* USB e non può fare da *host* per un mouse sullo stesso cavo. Combinazione che funziona: **video via USB + input via Bluetooth**.

---

## Architettura proposta

Il nucleo non deve sapere da dove arrivano i tocchi.

```
core/
  video/   VideoSource   (interfaccia: next_frame())
  input/   InputBackend  (interfaccia: tap(x,y), drag, scroll, key)
  ui/      finestra con frame + cattura mouse/tastiera
  calib/   mapping coordinate e calibrazione
```

- La UI converte i click sulla finestra in **coordinate normalizzate (0..1)** e le passa al backend attivo.
- Auto-detect all'avvio (jailbreak raggiungibile? ESP32 su seriale?) con override manuale.

### VideoSource (da implementare 2-3 sorgenti selezionabili)

| Sorgente | Pro | Contro |
|---|---|---|
| `pymobiledevice3` (screenshot via DVT) | Multipiattaforma, via USB | Pochi fps (~5-15) |
| AVFoundation / CoreMediaIO (macOS) | Stesso canale di QuickTime, fluido, USB | Solo macOS |
| UxPlay (AirPlay) | fps alti | Wireless |
| Adattatore Lightning/USB-C → HDMI + capture card | Più robusto, bassa latenza | Hardware extra |

### InputBackend: ESP32 (mouse BLE HID)

- Firmware con libreria **ESP32-BLE-Mouse**.
- Protocollo binario semplice via seriale o UDP: `MOVE dx dy`, `BTN`, `SCROLL`.
- Il delta per singolo movimento è **int8**: spezzare i delta grandi in chunk.
- Il driver sul PC mantiene una **posizione stimata del cursore**. Ricalibrazione: invio di molti delta negativi fino all'angolo (0,0), poi movimento in relativo.
- Per correggere deriva e accelerazione: rilevare il cursore AssistiveTouch nel frame video con **template matching** e chiudere il loop (feedback video). È la parte che rende il sistema preciso.
- Consigliato abbassare la velocità di tracciamento in AssistiveTouch e calibrare empiricamente.
- Swipe da bordo gestiti tramite azioni AssistiveTouch assegnate ai tasti del mouse.
- Alternative all'ESP32: Raspberry Pi Zero W / Pi con BlueZ in modalità HID, oppure il PC stesso se il suo adattatore Bluetooth supporta il ruolo peripheral.

### InputBackend: Jailbreak

- Piccolo **daemon on-device** che espone un socket TCP/Unix con comandi `touch_down / touch_move / touch_up x y`.
- Inietta eventi digitizer via **IOHIDEvent**.
- Coordinate assolute: nessuna calibrazione, supporto multitouch e pinch.
- Su **rootless** (Dopamine, palera1n) percorsi, permessi ed entitlement cambiano: verificare cosa permette il setup specifico.
- Alternativa senza scrivere il daemon: usare **WebDriverAgent** come backend separato.

---

## Stack consigliato

- **Python** + `pymobiledevice3` + **OpenCV** + **PyQt6** (oppure UI web con WebSocket per controllo remoto).
- Se serve latenza minima sul video, valutare Rust/Go per quella parte, ma partire in Python.

---

## Ordine di sviluppo

1. `VideoSource` + finestra (validare la latenza).
2. Backend ESP32 senza loop chiuso (click e mouse relativo).
3. Calibrazione con template matching del cursore AssistiveTouch.
4. Daemon jailbreak come backend alternativo.

---

## Da definire prima di iniziare

- **OS del PC** (cambia la scelta della sorgente video: su macOS AVFoundation è l'opzione migliore).
- **Versione iOS e tipo di jailbreak** (rootful/rootless, palera1n, Dopamine, ecc.) per il backend jailbreak.
- Modello di ESP32 disponibile (serve il supporto BLE: ESP32 classico, S3, C3).
- Se serve controllo remoto (UI web) oppure solo finestra locale.

## Prossimi passi suggeriti per Claude Code

1. Creare lo scheletro del repository con le interfacce `VideoSource` e `InputBackend`.
2. Implementare la finestra PyQt6 con visualizzazione frame e mapping click → coordinate normalizzate.
3. Scrivere il firmware ESP32 (ESP32-BLE-Mouse) con il protocollo binario e il relativo driver Python.
4. Implementare auto-detection dei backend e selezione manuale.
