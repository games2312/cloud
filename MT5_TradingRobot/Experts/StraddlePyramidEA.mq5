//+------------------------------------------------------------------+
//|                                   StraddlePyramidEA.mq5           |
//|                          GenSpark AI Developer                    |
//|  Strategie:                                                       |
//|   - Deploye en M15, analyse de tendance sur TF superieure (EMA)   |
//|   - A l'ouverture de chaque bougie M15 : ouvre 1 BUY + 1 SELL     |
//|   - Selon le deplacement de la bougie (seuil ATR) : ferme la      |
//|     position perdante, renforce le sens gagnant (2-3 entrees)     |
//|     UNIQUEMENT si conforme a la tendance TF haute                 |
//|   - Trailing stop pour laisser courir les gains                   |
//|   - Fermeture en fin de bougie si pas de confirmation             |
//|   - Lot dynamique base sur ATR + % de risque                      |
//|   - Max 10 positions, stop de perte journaliere                   |
//+------------------------------------------------------------------+
#property copyright "GenSpark AI Developer"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include "../Include/RiskManager.mqh"

//==================================================================
//                          PARAMETRES (INPUTS)
//==================================================================
input group "=== Tendance (Timeframe superieure) ==="
input ENUM_TIMEFRAMES InpTrendTF        = PERIOD_H1;   // TF d'analyse de tendance
input int             InpEmaFast         = 50;          // EMA rapide
input int             InpEmaSlow         = 200;         // EMA lente

input group "=== Detection mouvement / ATR ==="
input ENUM_TIMEFRAMES InpAtrTF          = PERIOD_M15;  // TF pour l'ATR
input int             InpAtrPeriod       = 14;          // Periode ATR
input double          InpAtrTriggerMult  = 0.5;         // Mult. ATR pour declencher (mouvement bougie)
input double          InpAtrSlMult       = 1.5;         // Mult. ATR pour le Stop Loss
input double          InpAtrTpMult       = 2.0;         // Mult. ATR pour le Take Profit
input double          InpFixedTriggerPips= 0.0;         // Seuil fixe en pips (0 = utiliser ATR)

input group "=== Gestion du risque ==="
input double          InpRiskPercent     = 1.0;         // % risque du capital par trade
input double          InpMaxLot          = 1.0;         // Lot maximum de securite
input double          InpMaxDailyLossPct = 5.0;         // Perte journaliere max (%)
input int             InpMaxPositions    = 10;          // Nombre max de positions simultanees
input int             InpReinforceCount  = 2;           // Nb de positions ajoutees dans le bon sens (2 a 3)

input group "=== Trailing Stop ==="
input bool            InpUseTrailing     = true;        // Activer le trailing stop
input double          InpTrailAtrMult    = 1.0;         // Mult. ATR pour le trailing
input double          InpTrailStartAtr   = 1.0;         // Profit (en ATR) avant d'activer le trailing

input group "=== Filtres / Securite ==="
input int             InpMaxSpreadPoints = 30;          // Spread max autorise (points)
input bool            InpCloseEndOfBar   = true;        // Fermer en fin de bougie si pas de confirmation
input long            InpMagic           = 20240615;    // Magic number
input int             InpSlippage        = 20;          // Slippage (points)

//==================================================================
//                          OBJETS GLOBAUX
//==================================================================
CTrade        trade;
CRiskManager  risk;

int      hEmaFast = INVALID_HANDLE;
int      hEmaSlow = INVALID_HANDLE;
int      hAtr     = INVALID_HANDLE;

datetime g_lastBarTime = 0;     // pour detecter une nouvelle bougie M15
double   g_barOpenPrice= 0.0;   // prix d'ouverture de la bougie courante
bool     g_reinforced  = false; // si on a deja renforce sur cette bougie
double   g_pip         = 0.0;   // valeur d'un pip en prix

//--- Enum de tendance
enum ENUM_TREND { TREND_NONE=0, TREND_UP=1, TREND_DOWN=-1 };

//+------------------------------------------------------------------+
//| Initialisation                                                   |
//+------------------------------------------------------------------+
int OnInit(void)
  {
   //--- Verifier le mode hedging
   long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(margin_mode!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      Print("AVERTISSEMENT: Le compte n'est pas en mode HEDGING. ",
            "Cette strategie (BUY+SELL simultanes) requiert un compte hedging.");
     }

   //--- Configuration de l'objet trade
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);

   //--- Indicateurs
   hEmaFast = iMA(_Symbol,InpTrendTF,InpEmaFast,0,MODE_EMA,PRICE_CLOSE);
   hEmaSlow = iMA(_Symbol,InpTrendTF,InpEmaSlow,0,MODE_EMA,PRICE_CLOSE);
   hAtr     = iATR(_Symbol,InpAtrTF,InpAtrPeriod);

   if(hEmaFast==INVALID_HANDLE || hEmaSlow==INVALID_HANDLE || hAtr==INVALID_HANDLE)
     {
      Print("Erreur creation des handles d'indicateurs");
      return(INIT_FAILED);
     }

   //--- Init gestion du risque
   risk.Init(_Symbol,InpRiskPercent,InpMaxLot,InpMaxDailyLossPct);

   //--- Calcul de la valeur d'un pip
   int    digits = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   g_pip = (digits==3 || digits==5) ? point*10.0 : point;

   g_lastBarTime = iTime(_Symbol,PERIOD_M15,0);

   Print("StraddlePyramidEA initialise. Symbole=",_Symbol," PIP=",g_pip);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Deinitialisation                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(hEmaFast!=INVALID_HANDLE) IndicatorRelease(hEmaFast);
   if(hEmaSlow!=INVALID_HANDLE) IndicatorRelease(hEmaSlow);
   if(hAtr!=INVALID_HANDLE)     IndicatorRelease(hAtr);
  }

//+------------------------------------------------------------------+
//| Recupere la valeur actuelle de l'ATR                             |
//+------------------------------------------------------------------+
double GetATR(void)
  {
   double buf[];
   ArraySetAsSeries(buf,true);
   if(CopyBuffer(hAtr,0,0,1,buf)<1) return(0.0);
   return(buf[0]);
  }

//+------------------------------------------------------------------+
//| Determine la tendance sur la TF superieure                       |
//+------------------------------------------------------------------+
ENUM_TREND GetTrend(void)
  {
   double f[],s[];
   ArraySetAsSeries(f,true);
   ArraySetAsSeries(s,true);
   if(CopyBuffer(hEmaFast,0,0,1,f)<1) return(TREND_NONE);
   if(CopyBuffer(hEmaSlow,0,0,1,s)<1) return(TREND_NONE);

   if(f[0]>s[0]) return(TREND_UP);
   if(f[0]<s[0]) return(TREND_DOWN);
   return(TREND_NONE);
  }

//+------------------------------------------------------------------+
//| Calcule le seuil de declenchement du mouvement (en prix)         |
//+------------------------------------------------------------------+
double GetTriggerDistance(void)
  {
   if(InpFixedTriggerPips>0.0)
      return(InpFixedTriggerPips*g_pip);

   double atr = GetATR();
   return(atr*InpAtrTriggerMult);
  }

//+------------------------------------------------------------------+
//| Compte les positions de l'EA (par type optionnel)                |
//+------------------------------------------------------------------+
int CountPositions(int type=-1)
  {
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if(type>=0 && (int)PositionGetInteger(POSITION_TYPE)!=type) continue;
      count++;
     }
   return(count);
  }

//+------------------------------------------------------------------+
//| Profit total flottant de l'EA pour un type donne                 |
//+------------------------------------------------------------------+
double TypeProfit(int type)
  {
   double profit=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if((int)PositionGetInteger(POSITION_TYPE)!=type) continue;
      profit+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
     }
   return(profit);
  }

//+------------------------------------------------------------------+
//| Ferme toutes les positions d'un type donne                       |
//+------------------------------------------------------------------+
void CloseAllByType(int type)
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if((int)PositionGetInteger(POSITION_TYPE)!=type) continue;
      trade.PositionClose(ticket);
     }
  }

//+------------------------------------------------------------------+
//| Ferme TOUTES les positions de l'EA                               |
//+------------------------------------------------------------------+
void CloseAll(void)
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      trade.PositionClose(ticket);
     }
  }

//+------------------------------------------------------------------+
//| Verifie le spread                                                |
//+------------------------------------------------------------------+
bool SpreadOK(void)
  {
   long spread = SymbolInfoInteger(_Symbol,SYMBOL_SPREAD);
   return(spread<=InpMaxSpreadPoints);
  }

//+------------------------------------------------------------------+
//| Ouvre une position (BUY ou SELL) avec SL/TP bases sur ATR        |
//+------------------------------------------------------------------+
bool OpenPosition(ENUM_ORDER_TYPE type,double atr,string comment)
  {
   if(CountPositions()>=InpMaxPositions)
     {
      Print("Limite de positions atteinte (",InpMaxPositions,")");
      return(false);
     }
   if(!SpreadOK())
     {
      Print("Spread trop eleve, ordre annule");
      return(false);
     }

   double sl_dist = atr*InpAtrSlMult;
   double tp_dist = atr*InpAtrTpMult;
   if(sl_dist<=0.0) return(false);

   //--- Respecter la distance minimale d'arret imposee par le broker
   double point     = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   double min_stop  = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*point;
   if(min_stop>0.0)
     {
      if(sl_dist<min_stop) sl_dist=min_stop;
      if(tp_dist<min_stop) tp_dist=min_stop;
     }

   double lot = risk.CalcLotByRisk(sl_dist);
   if(lot<=0.0) return(false);

   double price,sl,tp;
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);

   if(type==ORDER_TYPE_BUY)
     {
      price = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      sl    = NormalizeDouble(price-sl_dist,digits);
      tp    = NormalizeDouble(price+tp_dist,digits);
      return(trade.Buy(lot,_Symbol,price,sl,tp,comment));
     }
   else
     {
      price = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      sl    = NormalizeDouble(price+sl_dist,digits);
      tp    = NormalizeDouble(price-tp_dist,digits);
      return(trade.Sell(lot,_Symbol,price,sl,tp,comment));
     }
  }

//+------------------------------------------------------------------+
//| Trailing stop base sur ATR                                       |
//+------------------------------------------------------------------+
void ManageTrailing(double atr)
  {
   if(!InpUseTrailing || atr<=0.0) return;

   int    digits = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double trail  = atr*InpTrailAtrMult;
   double start  = atr*InpTrailStartAtr;

   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;

      int    ptype = (int)PositionGetInteger(POSITION_TYPE);
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double cursl = PositionGetDouble(POSITION_SL);
      double curtp = PositionGetDouble(POSITION_TP);

      if(ptype==POSITION_TYPE_BUY)
        {
         double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
         if(bid-open>=start)
           {
            double newsl = NormalizeDouble(bid-trail,digits);
            if(newsl>cursl)
               trade.PositionModify(ticket,newsl,curtp);
           }
        }
      else if(ptype==POSITION_TYPE_SELL)
        {
         double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
         if(open-ask>=start)
           {
            double newsl = NormalizeDouble(ask+trail,digits);
            if(newsl<cursl || cursl==0.0)
               trade.PositionModify(ticket,newsl,curtp);
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Logique a l'ouverture d'une nouvelle bougie M15                  |
//+------------------------------------------------------------------+
void OnNewBar(double atr,ENUM_TREND trend)
  {
   //--- 1) Fin de bougie precedente : fermer si pas de confirmation
   if(InpCloseEndOfBar)
     {
      //--- Confirmation de continuite = le sens gagnant est conforme a la tendance
      //--- Si non confirme, on solde tout pour repartir proprement.
      double buyP  = TypeProfit(POSITION_TYPE_BUY);
      double sellP = TypeProfit(POSITION_TYPE_SELL);
      bool confirmed=false;

      if(trend==TREND_UP   && buyP>0)  confirmed=true;
      if(trend==TREND_DOWN && sellP>0) confirmed=true;

      if(!confirmed)
         CloseAll();   // pas de confirmation -> on prend les acquis / on coupe
     }

   //--- 2) Ouverture du straddle initial (BUY + SELL) sur la nouvelle bougie
   g_barOpenPrice = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   g_reinforced   = false;

   if(atr<=0.0) return;

   //--- On ouvre le straddle seulement s'il reste de la place
   if(CountPositions()+2<=InpMaxPositions)
     {
      OpenPosition(ORDER_TYPE_BUY ,atr,"straddle_buy");
      OpenPosition(ORDER_TYPE_SELL,atr,"straddle_sell");
     }
  }

//+------------------------------------------------------------------+
//| Logique intra-bougie : detecter le mouvement et renforcer        |
//+------------------------------------------------------------------+
void OnIntraBar(double atr,ENUM_TREND trend)
  {
   if(g_reinforced) { ManageTrailing(atr); return; }
   if(atr<=0.0)     return;

   double trigger = GetTriggerDistance();
   if(trigger<=0.0) return;

   double price = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double move  = price - g_barOpenPrice;   // >0 = hausse, <0 = baisse

   //--- Le mouvement a-t-il atteint le seuil de declenchement ?
   if(MathAbs(move)<trigger) { ManageTrailing(atr); return; }

   //--- Sens du mouvement
   bool moveUp = (move>0);

   //--- FILTRE DE SECURITE : on ne renforce que dans le sens de la tendance TF haute
   bool alignUp   = (moveUp  && trend==TREND_UP);
   bool alignDown = (!moveUp && trend==TREND_DOWN);

   if(!alignUp && !alignDown)
     {
      //--- Mouvement contre la tendance : on ferme la position perdante
      //--- (le sens contraire au mouvement) mais on ne renforce pas.
      if(moveUp) CloseAllByType(POSITION_TYPE_SELL);
      else       CloseAllByType(POSITION_TYPE_BUY);
      ManageTrailing(atr);
      return;
     }

   //--- Mouvement aligne avec la tendance : on ferme le perdant et on renforce
   if(alignUp)
     {
      CloseAllByType(POSITION_TYPE_SELL);   // ferme le perdant
      for(int i=0;i<InpReinforceCount;i++)
         if(CountPositions()<InpMaxPositions)
            OpenPosition(ORDER_TYPE_BUY,atr,"reinforce_buy");
     }
   else // alignDown
     {
      CloseAllByType(POSITION_TYPE_BUY);    // ferme le perdant
      for(int i=0;i<InpReinforceCount;i++)
         if(CountPositions()<InpMaxPositions)
            OpenPosition(ORDER_TYPE_SELL,atr,"reinforce_sell");
     }

   g_reinforced = true;
   ManageTrailing(atr);
  }

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick(void)
  {
   //--- Stop global de perte journaliere
   if(risk.IsDailyLossExceeded())
     {
      CloseAll();
      return;
     }

   double     atr   = GetATR();
   ENUM_TREND trend = GetTrend();

   //--- Detection d'une nouvelle bougie M15
   datetime curBar = iTime(_Symbol,PERIOD_M15,0);
   if(curBar!=g_lastBarTime)
     {
      g_lastBarTime = curBar;
      OnNewBar(atr,trend);
      return;
     }

   //--- Logique intra-bougie
   OnIntraBar(atr,trend);
  }
//+------------------------------------------------------------------+
