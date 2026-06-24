//+------------------------------------------------------------------+
//|                                              RiskManager.mqh      |
//|                          Module de gestion du risque (ATR-based)  |
//+------------------------------------------------------------------+
#property copyright "GenSpark AI Developer"
#property strict

//+------------------------------------------------------------------+
//| Classe de gestion du risque                                      |
//| - Calcul du lot dynamique basé sur l'ATR et le % de risque       |
//| - Normalisation du lot selon les contraintes du broker           |
//| - Contrôle de la perte journalière (stop global)                 |
//+------------------------------------------------------------------+
class CRiskManager
  {
private:
   string            m_symbol;
   double            m_risk_percent;     // % de capital risqué par trade
   double            m_max_lot;          // plafond de lot de sécurité
   double            m_day_start_equity; // equity au début de la journée
   double            m_max_daily_loss_pct; // perte journalière max en %
   datetime          m_current_day;      // jour courant (pour reset)

public:
                     CRiskManager(void);
   void              Init(const string symbol,double risk_percent,double max_lot,double max_daily_loss_pct);

   //--- Calcul du lot dynamique : risque = Capital * %risque
   //--- distance de SL (en points) dérivée de l'ATR
   double            CalcLotByRisk(double sl_distance_price);

   //--- Normalisation du lot selon volume min/max/step du broker
   double            NormalizeLot(double lot);

   //--- Gestion de la perte journalière
   void              UpdateDailyEquity(void);
   bool              IsDailyLossExceeded(void);
   double            DayStartEquity(void){ return m_day_start_equity; }
  };

//+------------------------------------------------------------------+
CRiskManager::CRiskManager(void)
  {
   m_symbol            = _Symbol;
   m_risk_percent      = 1.0;
   m_max_lot           = 1.0;
   m_day_start_equity  = 0.0;
   m_max_daily_loss_pct= 5.0;
   m_current_day       = 0;
  }

//+------------------------------------------------------------------+
void CRiskManager::Init(const string symbol,double risk_percent,double max_lot,double max_daily_loss_pct)
  {
   m_symbol             = symbol;
   m_risk_percent       = risk_percent;
   m_max_lot            = max_lot;
   m_max_daily_loss_pct = max_daily_loss_pct;
   UpdateDailyEquity();
  }

//+------------------------------------------------------------------+
//| Calcul du lot en fonction du risque et de la distance de SL      |
//| sl_distance_price : distance du SL exprimée en prix (ex: 0.0025) |
//+------------------------------------------------------------------+
double CRiskManager::CalcLotByRisk(double sl_distance_price)
  {
   if(sl_distance_price<=0.0)
      return(NormalizeLot(SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN)));

   double balance      = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk_money   = balance * (m_risk_percent/100.0);

   double tick_value   = SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_VALUE);
   double tick_size    = SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_SIZE);

   if(tick_value<=0.0 || tick_size<=0.0)
      return(NormalizeLot(SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN)));

   //--- Perte pour 1 lot si le SL est touché
   double loss_per_lot = (sl_distance_price/tick_size) * tick_value;
   if(loss_per_lot<=0.0)
      return(NormalizeLot(SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN)));

   double lot = risk_money / loss_per_lot;

   return(NormalizeLot(lot));
  }

//+------------------------------------------------------------------+
//| Normalise le lot selon les contraintes du broker                 |
//+------------------------------------------------------------------+
double CRiskManager::NormalizeLot(double lot)
  {
   double vol_min  = SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN);
   double vol_max  = SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MAX);
   double vol_step = SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_STEP);

   //--- Appliquer le plafond de sécurité utilisateur
   if(m_max_lot>0.0 && vol_max>m_max_lot)
      vol_max = m_max_lot;

   if(vol_step<=0.0) vol_step = 0.01;

   //--- Arrondir au step inférieur
   lot = MathFloor(lot/vol_step)*vol_step;

   if(lot<vol_min) lot = vol_min;
   if(lot>vol_max) lot = vol_max;

   //--- Nettoyage des arrondis flottants
   int digits = (int)MathRound(MathLog10(1.0/vol_step));
   if(digits<0) digits=0;
   lot = NormalizeDouble(lot,digits);

   return(lot);
  }

//+------------------------------------------------------------------+
//| Met à jour l'equity de référence au changement de journée        |
//+------------------------------------------------------------------+
void CRiskManager::UpdateDailyEquity(void)
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(),dt);
   dt.hour=0; dt.min=0; dt.sec=0;
   datetime day_start = StructToTime(dt);

   if(day_start!=m_current_day)
     {
      m_current_day      = day_start;
      m_day_start_equity = AccountInfoDouble(ACCOUNT_EQUITY);
     }
  }

//+------------------------------------------------------------------+
//| Vérifie si la perte journalière maximale est dépassée            |
//+------------------------------------------------------------------+
bool CRiskManager::IsDailyLossExceeded(void)
  {
   UpdateDailyEquity();
   if(m_day_start_equity<=0.0) return(false);

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double loss_pct = (m_day_start_equity-equity)/m_day_start_equity*100.0;

   return(loss_pct >= m_max_daily_loss_pct);
  }
//+------------------------------------------------------------------+
