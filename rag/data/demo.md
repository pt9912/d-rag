# GraphRAG: Häufig gestellte Fragen zu verantwortungsvoller KI

## Was ist GraphRAG?

GraphRAG ist eine KI-basierte Funktion zur Inhaltsinterpretation und -suche. Mithilfe von LLMs analysiert es Daten, um einen Wissensgraphen zu erstellen und Benutzerfragen zu einem vom Benutzer bereitgestellten privaten Datensatz zu beantworten.

## Was kann GraphRAG leisten?  

GraphRAG verknüpft Informationen aus großen Datenmengen und nutzt diese Verknüpfungen, um Fragen zu beantworten, die mit schlüsselwort- und vektorbasierten Suchmechanismen schwer oder gar nicht zu beantworten sind. Aufbauend auf der vorherigen Frage, geben Sie bitte allgemeinverständliche, semitechnische Informationen darüber, wie das System verschiedene Anwendungsfälle ermöglicht. So kann ein System, das GraphRAG verwendet, sowohl Fragen beantworten, deren Antworten sich über viele Dokumente erstrecken, als auch thematische Fragen wie „Was sind die wichtigsten Themen in diesem Datensatz?“.

## Wofür ist GraphRAG gedacht?

* GraphRAG ist für die Unterstützung kritischer Anwendungsfälle der Informationsfindung und -analyse gedacht, in denen die Informationen, die für eine nützliche Erkenntnis erforderlich sind, sich über viele Dokumente erstrecken, verrauscht sind, mit Fehlinformationen und/oder Desinformationen vermischt sind oder wenn die Fragen, die die Benutzer beantworten möchten, abstrakter oder thematischer sind, als die zugrunde liegenden Daten direkt beantworten können.
GraphRAG ist für Umgebungen konzipiert, in denen die Nutzer bereits in verantwortungsvollen Analysemethoden geschult sind und kritisches Denken erwartet wird. GraphRAG liefert zwar tiefgreifende Erkenntnisse zu komplexen Informationsthemen, jedoch ist eine menschliche Analyse der Antworten durch einen Fachexperten erforderlich, um die von GraphRAG generierten Ergebnisse zu überprüfen und zu ergänzen.
GraphRAG ist für den Einsatz mit einem domänenspezifischen Textdatenkorpus vorgesehen. GraphRAG selbst erhebt keine Nutzerdaten, Nutzern wird jedoch empfohlen, die Datenschutzrichtlinien des zur Konfiguration von GraphRAG verwendeten LLM zu überprüfen.

Wie wurde GraphRAG evaluiert? Welche Metriken werden zur Leistungsmessung verwendet?

GraphRAG wurde auf vielfältige Weise evaluiert. Die Hauptkriterien sind: 1) akkurate Darstellung des Datensatzes, 2) Transparenz und Nachvollziehbarkeit der Antworten, 3) Robustheit gegenüber Angriffen durch Eingabe von Schnellantworten und Datenkorpusmanipulation sowie 4) geringe Rate an Fehlinterpretationen. Die Details der einzelnen Evaluierungsmethoden sind unten nach Nummern aufgeführt.

1) Die korrekte Darstellung des Datensatzes wurde sowohl durch manuelle Inspektion als auch durch automatisierte Tests anhand einer „Referenzlösung“ überprüft, die aus zufällig ausgewählten Teilmengen eines Testkorpus erstellt wurde.

2) Die Transparenz und Fundiertheit der Antworten wird durch eine automatisierte Auswertung der Antwortabdeckung und eine menschliche Prüfung des zurückgegebenen Kontextes getestet.  

3) Wir testen sowohl User-Prompt-Injection-Angriffe („Jailbreaks“) als auch Cross-Prompt-Injection-Angriffe („Datenangriffe“) mit Hilfe manueller und halbautomatisierter Techniken.

4) Die Halluzinationsraten werden anhand von Kennzahlen zur Schadensdeckung, manueller Überprüfung der Antwort und der Quelle sowie durch gezielte Angriffe auf besonders anspruchsvolle Datensätze ermittelt, um eine erzwungene Halluzination hervorzurufen.

Was sind die Einschränkungen von GraphRAG? Wie können Benutzer die Auswirkungen der Einschränkungen von GraphRAG bei der Verwendung des Systems minimieren?

GraphRAG ist auf gut strukturierte Indexierungsbeispiele angewiesen. Für allgemeine Anwendungen (z. B. Inhalte zu Personen, Orten, Organisationen, Dingen usw.) stellen wir beispielhafte Indexierungsvorschläge bereit. Bei spezifischen Datensätzen hängt eine effektive Indexierung von der korrekten Identifizierung domänenspezifischer Konzepte ab.   

Die Indizierung ist ein relativ aufwändiger Vorgang; eine bewährte Methode zur Reduzierung des Indizierungsaufwands ist die Erstellung eines kleinen Testdatensatzes in der Zieldomäne, um die Leistungsfähigkeit des Indexers vor großen Indizierungsvorgängen sicherzustellen.

## Welche betrieblichen Faktoren und Einstellungen ermöglichen eine effektive und verantwortungsvolle Nutzung von GraphRAG?

GraphRAG ist für Anwender mit fundierten Fachkenntnissen und Erfahrung im Umgang mit komplexen Informationsherausforderungen konzipiert. Obwohl der Ansatz im Allgemeinen robust gegenüber Manipulationsangriffen und der Identifizierung widersprüchlicher Informationsquellen ist, richtet sich das System an vertrauenswürdige Anwender. Eine sorgfältige menschliche Analyse der Antworten ist wichtig, um verlässliche Erkenntnisse zu gewinnen, und die Herkunft der Informationen sollte nachvollziehbar sein, um die Übereinstimmung der Anwender mit den im Rahmen der Antwortgenerierung gezogenen Schlussfolgerungen sicherzustellen.

GraphRAG liefert die effektivsten Ergebnisse bei natürlichsprachlichen Textdaten, die sich alle auf ein übergeordnetes Thema konzentrieren und reich an Entitäten sind – wobei Entitäten Personen, Orte, Dinge oder Objekte sind, die eindeutig identifiziert werden können.

GraphRAG wurde zwar hinsichtlich seiner Widerstandsfähigkeit gegen Prompt- und Data-Corpus-Injection-Angriffe evaluiert und auf spezifische Schadensarten untersucht, jedoch kann das vom Benutzer mit GraphRAG konfigurierte LLM unangemessene oder anstößige Inhalte erzeugen. Daher ist der Einsatz in sensiblen Kontexten ohne zusätzliche, anwendungsfall- und modellspezifische Sicherheitsvorkehrungen unter Umständen nicht ratsam. Entwickler sollten die Ergebnisse kontextbezogen bewerten und verfügbare Sicherheitsklassifikatoren, modellspezifische Sicherheitsfilter und -funktionen (z. B. https://azure.microsoft.com/en-us/products/ai-services/ai-content-safety) oder benutzerdefinierte Lösungen, die für ihren Anwendungsfall geeignet sind, verwenden.