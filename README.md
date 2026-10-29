# MCP Bridge für Home Assistant

Verbinde Home Assistant mit Codex und anderen MCP-Clients – direkt über deine eigene Home-Assistant-Instanz. Der Agent kann Zustände lesen, Geräte steuern, Automationen bearbeiten, Backups verwalten und bei der erneuten Anmeldung von Integrationen helfen.

> **Status:** Version 0.2.0 · Home Assistant 2026.10 oder neuer · MIT-Lizenz
> Die Verbindung, OAuth und das Erstellen eines Backups wurden mit Home Assistant Core 2026.10.4 in einer getrennten Testinstanz geprüft. Eine Wiederherstellung auf HAOS und die Anmeldeflüsse einzelner Cloud-Anbieter sind noch nicht Ende zu Ende getestet.

## Möglichkeiten

| Bereich | Beispiele |
| --- | --- |
| Geräte und Entitäten | Zustände lesen, Services aufrufen, Geräte, Bereiche und Labels finden |
| Automationen | Auflisten, prüfen, erstellen, ändern, auslösen und Traces untersuchen |
| Skripte und Szenen | Lesen, erstellen, bearbeiten, ausführen und löschen |
| Home Assistant | Integrationen, Helfer, Dashboards, Logbuch, Historie und Reparaturen verwalten |
| Backup | Speicherorte ermitteln, Backup starten, Details abrufen und Wiederherstellung anfordern |
| Anmeldung | Re-Authentifizierungsflows bestehender Integrationen starten und fortsetzen |
| Erweiterte Funktionen | Templates auswerten und Home Assistants WebSocket-API verwenden |

Welche Toolgruppen und einzelnen Tools zur Verfügung stehen, lässt sich in den Integrationsoptionen auswählen. MCP Bridge unterstützt Streamable HTTP und den älteren HTTP/SSE-Transport.

## Voraussetzungen

- Home Assistant 2026.10 oder neuer, mit einer laufenden HTTP-Schnittstelle.
- Ein Home-Assistant-Benutzerkonto; für einige Tools ist ein Administratorkonto erforderlich.
- Ein MCP-Client, der Home Assistant über das Netzwerk erreichen kann.
- Für HACS: eine veröffentlichte Version dieses Repositories und eine installierte HACS-Integration.

Der Server läuft **innerhalb von Home Assistant Core**. Wenn Core nicht erreichbar ist, ist auch MCP Bridge nicht erreichbar. Ein Backup ist eine Home-Assistant-Sicherung der ausgewählten Inhalte, kein atomarer VM- oder Datenträger-Snapshot.

## Installation

### Über HACS

1. In HACS das Menü **⋮ → Benutzerdefinierte Repositories** öffnen.
2. `https://github.com/daMustermann/mcp-homeassistant` als Repository hinzufügen und die Kategorie **Integration** wählen.
3. **MCP Bridge** installieren und Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **MCP Bridge** suchen und die Einrichtung abschließen.

HACS lädt den auf GitHub veröffentlichten Stand. Lokale Änderungen erscheinen dort erst, nachdem sie in das Repository übertragen wurden. Falls HACS noch keine passende veröffentlichte Version anbietet, die manuelle Installation verwenden.

### Manuell

1. Den Ordner `custom_components/mcp_bridge` aus diesem Repository nach `/config/custom_components/mcp_bridge` auf dem Home-Assistant-System kopieren.
2. Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** **MCP Bridge** hinzufügen.

Bei einem Update den Integrationsordner ersetzen und Home Assistant neu starten. Die Home-Assistant-Daten unter `/config/.storage` gehören nicht zum Integrationsordner und bleiben erhalten.

## Mit Codex verbinden

Die MCP-Adresse lautet für eine lokale Installation beispielsweise:

```text
http://homeassistant:8123/mcp_bridge/mcp
```

In einem Terminal mit installierter Codex CLI:

```bash
codex mcp add home-assistant --url http://homeassistant:8123/mcp_bridge/mcp
codex mcp login home-assistant
codex mcp list
```

Beim Login öffnet Codex den Home-Assistant-Anmeldefluss. Die Verbindung funktioniert nur, wenn Codex die angegebene Adresse erreichen kann. Andere MCP-Clients können dieselbe URL und OAuth-Erkennung nutzen; je nach Client kann HTTPS erforderlich sein.

Bei Problemen mit der Anmeldung kann alternativ ein langlebiges Home-Assistant-Zugriffstoken als Bearer-Token verwendet werden. Codex kann es aus einer Umgebungsvariable lesen:

```toml
[mcp_servers.home-assistant]
url = "http://homeassistant:8123/mcp_bridge/mcp"
bearer_token_env_var = "HOME_ASSISTANT_TOKEN"
```

Die Umgebungsvariable muss für den Codex-Prozess gesetzt sein. Den Token nicht in das Repository oder in Screenshots schreiben. In den Integrationsoptionen lässt sich die Annahme von Home-Assistant-Tokens abschalten.

## Backups und Wiederherstellung

Für größere Änderungen sollte der Agent zuerst ein Backup erstellen und dessen Abschluss, Inhalt und Speicherort prüfen:

1. `list_backup_locations` zeigt die tatsächlich verfügbaren Backup-Ziele.
2. `create_backup` startet eine Sicherung. Ohne zusätzliche Einstellungen verwendet es die konfigurierten automatischen Backup-Einstellungen. Für eigene Einstellungen `agent_ids` aus Schritt 1 angeben; standardmäßig werden Home Assistant, Datenbank, alle Add-ons und die Ordner `share`, `addons/local`, `ssl` und `media` angefragt. Der tatsächlich gesicherte Umfang muss anschließend geprüft werden.
3. `list_backups` zeigt den Status und vorhandene Sicherungen; `get_backup_details` zeigt die Details einer bestimmten Sicherung.
4. `restore_backup` fordert die Wiederherstellung einer ausgewählten Sicherung von einem angegebenen Speicherort an. Dabei können aktuelle Daten überschrieben und die Verbindung unterbrochen werden.

Der Agent erhält die Anweisung, vor größeren Änderungen eine geeignete Sicherung zu prüfen; dies ist keine technisch erzwungene automatische Sicherung vor jedem Toolaufruf. Backup-Umfang, verfügbare Speicherorte und Verschlüsselung hängen von deiner Home-Assistant-Konfiguration ab. Bewahre den Verschlüsselungsschlüssel und nach Möglichkeit eine Kopie der Sicherung außerhalb des Systems auf. Teste eine Wiederherstellung auf einer geeigneten Testinstallation.

## Abgelaufene Anmeldungen

`list_integrations` zeigt bestehende Integrationen. Mit `start_reauthentication` kann ein dafür unterstützter Re-Authentifizierungsflow gestartet werden; `continue_flow` führt durch die nächsten Schritte. Ist bereits ein Flow aktiv, zeigt `list_flows_in_progress` dessen ID.

OAuth-Anmeldung, E-Mail-Code, MFA oder eine Bestätigung beim Anbieter können weitere Schritte erfordern. Der Agent kann dafür separat verfügbare Browser- oder E-Mail-Werkzeuge verwenden oder dich um Hilfe bitten. MCP Bridge enthält selbst keinen E-Mail-Client und keine automatische Anbieteranmeldung. Ob und wie das bei Home Connect, Dreame, Tuya oder Xiaomi funktioniert, hängt von der jeweiligen Integration und dem Anbieter ab.

## Konfiguration

Unter **Einstellungen → Geräte & Dienste → MCP Bridge → Konfigurieren** findest du:

- **Toolgruppen und einzelne Tools:** Funktionen ausblenden oder zulassen.
- **Entity exposure:** Entitäten nach Domain, Entity, Bereich oder Label filtern.
- **Security:** Schreibschutz, disruptive Tools, Administratorpflicht, Tokenannahme und Antwortgröße einstellen.
- **Connected clients:** verbundene OAuth-Clients anzeigen und widerrufen.

Zum Kennenlernen ist der Schreibschutz ein guter Start. Beachte: Entity-Filter gelten für viele dedizierte Tools, sind aber keine vollständige Zugriffsschranke für alle indirekten Wege. Insbesondere Template-Auswertung und der rohe WebSocket-Zugriff können darüber hinausreichen. OAuth-Scopes werden derzeit gespeichert, aber nicht unabhängig pro Tool durchgesetzt; die Integrationsoptionen und das Home-Assistant-Konto bestimmen den verfügbaren Zugriff.

## Fehlerbehebung

- **404 am MCP-Endpunkt:** Prüfen, ob der Ordner richtig liegt, Home Assistant nach der Installation neu gestartet wurde und MCP Bridge unter Geräte & Dienste eingerichtet ist.
- **Anmeldung funktioniert nicht:** Prüfen, ob der Client den verwendeten Hostnamen erreicht und ob der OAuth-Callback des Clients erreichbar ist. Bei Reverse-Proxies müssen Home Assistants Proxy-Einstellungen zum Aufbau passen.
- **Tool fehlt:** Toolgruppe, einzelne Tools, Schreibschutz und Administratorstatus in den Optionen prüfen. Einige Funktionen benötigen Supervisor oder weitere Home-Assistant-Integrationen.
- **Backup nicht sichtbar:** Der Auftrag läuft möglicherweise noch oder der gewählte Speicherort hat einen Fehler gemeldet. `list_backups` und `get_backup_details` prüfen.
- **Integration nicht erreichbar:** Die Bridge läuft nur, solange Home Assistant Core funktioniert. Bei einem Core-Ausfall die regulären Home-Assistant-Wiederherstellungswege verwenden.

## Entwicklung und Tests

Die Integration liegt unter `custom_components/mcp_bridge/`; `dev/scripts/` enthält MCP-, OAuth- und PKCE-Tests. Die lokalen Tests ohne Home Assistant laufen mit:

```bash
python -m unittest discover -s tests
```

Für echte Integrationstests eine separate Home-Assistant-Instanz verwenden. Tests, die Sicherungen wiederherstellen oder Geräte steuern, gehören nicht auf ein produktives System.

## Lizenz

[MIT](LICENSE)
