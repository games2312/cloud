# 🤖 StraddlePyramidEA — Robot de Trading MT5

Expert Advisor (EA) pour MetaTrader 5 implémentant une stratégie de **straddle + pyramidage avec hedging**, pilotée par la tendance d'une timeframe supérieure et par l'ATR pour la gestion dynamique du risque.

---

## 📋 Table des matières
1. [Principe de la stratégie](#principe)
2. [Installation](#installation)
3. [Paramètres (Inputs)](#parametres)
4. [Logique détaillée](#logique)
5. [Gestion du risque](#risque)
6. [⚠️ Avertissements importants](#avertissements)
7. [Conseils de réglage et backtest](#reglage)

---

## <a name="principe"></a>1. Principe de la stratégie

- **Timeframe d'exécution** : M15 (à attacher sur un graphique M15).
- **Analyse de tendance** : sur une timeframe supérieure (H1 par défaut) via le croisement **EMA 50 / EMA 200** — l'indicateur de tendance le plus utilisé.
- **À chaque nouvelle bougie M15** : ouverture simultanée d'un **BUY** et d'un **SELL** (straddle) — nécessite un **compte HEDGING**.
- **Pendant la bougie** : dès que le prix se déplace d'un certain montant (seuil dynamique = `ATR × multiplicateur`), on :
  - **Ferme la position perdante** (sens opposé au mouvement),
  - **Renforce le sens gagnant** avec 2 à 3 positions supplémentaires — **uniquement si le mouvement est aligné avec la tendance de la TF supérieure** (filtre de sécurité clé).
- **Laisser courir** : géré par un **trailing stop basé sur l'ATR**.
- **Fin de bougie** : si la continuité n'est pas confirmée (sens gagnant non conforme à la tendance), toutes les positions sont **fermées** pour repartir proprement.
- **Lot dynamique** : calculé en continu à partir de l'**ATR** et d'un **% de risque** du capital.
- **Garde-fous** : maximum **10 positions** simultanées, **stop de perte journalière**, contrôle du **spread**.

---

## <a name="installation"></a>2. Installation

1. Ouvrez MetaTrader 5 → menu **Fichier → Ouvrir le dossier de données**.
2. Copiez les fichiers :
   - `Experts/StraddlePyramidEA.mq5` → dossier `MQL5/Experts/`
   - `Include/RiskManager.mqh` → dossier `MQL5/Include/` 
     *(ou conservez la structure et ajustez le chemin `#include`)*.
3. Ouvrez **MetaEditor** (F4), ouvrez `StraddlePyramidEA.mq5`, puis cliquez sur **Compiler** (F7). Aucune erreur ne doit apparaître.
4. Dans MT5, glissez l'EA sur un graphique **M15** du symbole souhaité.
5. Autorisez le **trading algorithmique** (bouton "AutoTrading" en vert).

> **Note sur le `#include`** : le code utilise `#include "../Include/RiskManager.mqh"`.  
> Si vous placez les deux fichiers directement dans `MQL5/Experts/` et `MQL5/Include/`,  
> remplacez cette ligne par `#include <RiskManager.mqh>`.

---

## <a name="parametres"></a>3. Paramètres (Inputs)

### Tendance (TF supérieure)
| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `InpTrendTF` | H1 | Timeframe d'analyse de tendance |
| `InpEmaFast` | 50 | Période EMA rapide |
| `InpEmaSlow` | 200 | Période EMA lente |

### Détection mouvement / ATR
| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `InpAtrTF` | M15 | TF de calcul de l'ATR |
| `InpAtrPeriod` | 14 | Période ATR |
| `InpAtrTriggerMult` | 0.5 | Mult. ATR → seuil de déclenchement du mouvement |
| `InpAtrSlMult` | 1.5 | Mult. ATR → distance du Stop Loss |
| `InpAtrTpMult` | 2.0 | Mult. ATR → distance du Take Profit |
| `InpFixedTriggerPips` | 0.0 | Seuil **fixe** en pips (0 = utiliser l'ATR) |

### Gestion du risque
| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `InpRiskPercent` | 1.0 | % du capital risqué par position |
| `InpMaxLot` | 1.0 | Plafond de lot de sécurité |
| `InpMaxDailyLossPct` | 5.0 | Perte journalière max (%) → ferme tout |
| `InpMaxPositions` | 10 | Nombre max de positions simultanées |
| `InpReinforceCount` | 2 | Positions ajoutées dans le bon sens (2 à 3) |

### Trailing Stop
| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `InpUseTrailing` | true | Activer le trailing stop |
| `InpTrailAtrMult` | 1.0 | Mult. ATR pour la distance de trailing |
| `InpTrailStartAtr` | 1.0 | Profit (en ATR) avant d'activer le trailing |

### Filtres / Sécurité
| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `InpMaxSpreadPoints` | 30 | Spread max autorisé (points) |
| `InpCloseEndOfBar` | true | Fermer en fin de bougie si pas de confirmation |
| `InpMagic` | 20240615 | Magic number (identifiant des trades de l'EA) |
| `InpSlippage` | 20 | Slippage autorisé (points) |

---

## <a name="logique"></a>4. Logique détaillée

```
À CHAQUE TICK :
  ├─ Perte journalière dépassée ? → fermer tout, stop
  ├─ Calcul ATR + tendance (EMA TF haute)
  │
  ├─ NOUVELLE BOUGIE M15 ?
  │    ├─ (fin bougie précédente) Pas de confirmation ? → fermer tout
  │    └─ Ouvrir straddle : 1 BUY + 1 SELL
  │
  └─ INTRA-BOUGIE :
       ├─ Mouvement < seuil (ATR×mult) → trailing stop seulement
       └─ Mouvement ≥ seuil :
            ├─ Aligné avec la tendance ? 
            │     → fermer le perdant + renforcer (2-3 positions)
            └─ Contre la tendance ?
                  → fermer le perdant, NE PAS renforcer
       └─ Trailing stop sur toutes les positions
```

---

## <a name="risque"></a>5. Gestion du risque

### Calcul du lot dynamique
```
risque_argent = Capital × (InpRiskPercent / 100)
perte_par_lot = (distance_SL / tick_size) × tick_value
lot           = risque_argent / perte_par_lot   (puis normalisé + plafonné)
```
La distance du SL est dérivée de l'ATR (`ATR × InpAtrSlMult`), donc **le lot s'adapte automatiquement à la volatilité** : marché volatil → SL plus large → lot plus petit (risque constant).

### Stop de perte journalière
Si l'equity recule de plus de `InpMaxDailyLossPct` % par rapport à l'equity du début de journée, **toutes les positions sont fermées** et aucune nouvelle n'est ouverte jusqu'au lendemain.

---

## <a name="avertissements"></a>6. ⚠️ Avertissements importants

> **Cette stratégie comporte des risques élevés.** À lire attentivement :

1. **Hedging obligatoire** : ouvrir BUY + SELL simultanément requiert un compte hedging. L'EA vous avertit sinon.
2. **Coût du straddle** : ouvrir deux sens paie le spread deux fois. En marché sans direction (range), cela peut éroder le capital.
3. **Pyramidage** : ajouter des positions dans le sens gagnant amplifie les gains MAIS aussi les pertes en cas de retournement brutal. Le filtre de tendance et le trailing stop réduisent ce risque sans l'éliminer.
4. **Pas de garantie de gain** : aucun robot ne garantit des profits. Testez impérativement en **compte démo** d'abord.
5. **Backtest obligatoire** : utilisez le **Strategy Tester** de MT5 sur plusieurs mois/années avant tout usage réel.

---

## <a name="reglage"></a>7. Conseils de réglage et backtest

- **Démarrez en démo** avec `InpRiskPercent = 0.5` et `InpMaxLot` bas.
- **Optimisez** `InpAtrTriggerMult` (0.3–0.8) et `InpAtrSlMult` (1.0–2.5) dans le Strategy Tester.
- Si votre actif est très volatil (indices, crypto), augmentez `InpMaxSpreadPoints`.
- Vérifiez que `InpTrendTF` correspond à votre style : H1 pour intraday réactif, H4 pour tendances plus larges.
- Surveillez le **journal "Experts"** pour les messages de l'EA (spread, limites, etc.).

---

*Développé par GenSpark AI Developer. Utilisez à vos propres risques — le trading comporte un risque de perte en capital.*
