import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Any
import aiohttp
import base58
import telebot
#from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration des APIs
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "6312658d-1fb5-4693-ae62-faa2684c6d11")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7583618651:AAFvMo9su7DE2FW203HjOk5NxJI8Uem0mGg")

# URLs des APIs
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

class SolanaAnalyzer:
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def is_valid_mint(self, mint: str) -> bool:
        """Vérifie si le mint address est valide"""
        if not mint or len(mint) < 32 or len(mint) > 44:
            return False
        try:
            base58.b58decode(mint)
            return True
        except Exception:
            return False
    
    async def get_dexscreener_data(self, mint: str) -> Dict[str, Any]:
        """Récupère les données de DexScreener"""
        try:
            url = DEXSCREENER_URL.format(mint)
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("pairs"):
                        # Agrégation des données de toutes les paires
                        pairs = data["pairs"]
                        total_volume = sum(float(pair.get("volume", {}).get("h24", 0)) for pair in pairs)
                        total_liquidity = sum(float(pair.get("liquidity", {}).get("usd", 0)) for pair in pairs)
                        
                        # Prendre le prix de la première paire disponible
                        price_usd = 0
                        price_change_24h = 0
                        
                        for pair in pairs:
                            if pair.get("priceUsd"):
                                price_usd = float(pair["priceUsd"])
                                price_change_24h = float(pair.get("priceChange", {}).get("h24", 0))
                                break
                        
                        return {
                            "pools": len(pairs),
                            "price_usd": price_usd,
                            "price_change_24h": price_change_24h,
                            "volume_24h": total_volume,
                            "liquidity": total_liquidity
                        }
        except Exception as e:
            logger.error(f"Erreur DexScreener: {e}")
        
        return {
            "pools": 0,
            "price_usd": 0,
            "price_change_24h": 0,
            "volume_24h": 0,
            "liquidity": 0
        }
    
    async def get_token_metadata(self, mint: str) -> Dict[str, Any]:
        """Récupère les métadonnées du token via Helius"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAsset",
                "params": {
                    "id": mint,
                    "displayOptions": {
                        "showFungible": True
                    }
                }
            }
            
            async with self.session.post(HELIUS_RPC_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("result", {})
                    
                    token_info = result.get("token_info", {})
                    supply = int(token_info.get("supply", 0))
                    decimals = int(token_info.get("decimals", 0))
                    
                    content = result.get("content", {})
                    metadata = content.get("metadata", {})
                    name = metadata.get("name", "Unknown")
                    symbol = metadata.get("symbol", "Unknown")
                    
                    # Tentative de récupération de la date de création
                    created_at = None
                    if result.get("mint_extensions"):
                        # Logique pour extraire la date si disponible
                        pass
                    
                    return {
                        "name": name,
                        "symbol": symbol,
                        "supply": supply,
                        "decimals": decimals,
                        "created_at": created_at
                    }
        except Exception as e:
            logger.error(f"Erreur Helius metadata: {e}")
        
        return {
            "name": "Unknown",
            "symbol": "Unknown",
            "supply": 0,
            "decimals": 0,
            "created_at": None
        }
    
    async def get_token_supply_info(self, mint: str) -> Dict[str, Any]:
        """Récupère les informations de supply via Solana RPC"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenSupply",
                "params": [mint]
            }
            
            async with self.session.post(SOLANA_RPC_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("result", {})
                    value = result.get("value", {})
                    
                    return {
                        "supply": int(value.get("amount", 0)),
                        "decimals": int(value.get("decimals", 0))
                    }
        except Exception as e:
            logger.error(f"Erreur Solana RPC supply: {e}")
        
        return {"supply": 0, "decimals": 0}
    
    async def get_holders_info_helius(self, mint: str) -> Dict[str, Any]:
        """Récupère les informations sur les holders via Helius API"""
        try:
            # Méthode 1: Utiliser getTokenAccounts pour récupérer les comptes de token
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccounts",
                "params": {
                    "mint": mint,
                    "limit": 1000,
                    "displayOptions": {
                        "showZeroBalance": False
                    }
                }
            }
            
            async with self.session.post(HELIUS_RPC_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("result", {})
                    token_accounts = result.get("token_accounts", [])
                    
                    if token_accounts:
                        # Calculer les métriques des holders
                        holders_data = []
                        for account in token_accounts:
                            amount = float(account.get("amount", 0))
                            if amount > 0:
                                holders_data.append({
                                    "address": account.get("address", ""),
                                    "amount": amount
                                })
                        
                        total_holders = len(holders_data)
                        
                        if total_holders > 0:
                            # Trier par montant décroissant
                            holders_data.sort(key=lambda x: x["amount"], reverse=True)
                            
                            # Calculer la part des 10 plus gros holders
                            top_10 = holders_data[:10]
                            total_supply = sum(holder["amount"] for holder in holders_data)
                            top_10_amount = sum(holder["amount"] for holder in top_10)
                            
                            top_10_share = (top_10_amount / total_supply) * 100 if total_supply > 0 else 0
                            
                            return {
                                "holders": total_holders,
                                "top_10_share": round(top_10_share, 2)
                            }
        except Exception as e:
            logger.error(f"Erreur Helius holders: {e}")
        
        # Méthode de fallback: Utiliser getProgramAccounts
        return await self.get_holders_info_fallback(mint)
    
    async def get_holders_info_fallback(self, mint: str) -> Dict[str, Any]:
        """Méthode de fallback pour récupérer les holders via getProgramAccounts"""
        try:
            # TOKEN_PROGRAM_ID pour Solana
            TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getProgramAccounts",
                "params": [
                    TOKEN_PROGRAM_ID,
                    {
                        "encoding": "jsonParsed",
                        "filters": [
                            {
                                "dataSize": 165
                            },
                            {
                                "memcmp": {
                                    "offset": 0,
                                    "bytes": mint
                                }
                            }
                        ]
                    }
                ]
            }
            
            async with self.session.post(SOLANA_RPC_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("result", [])
                    
                    holders_data = []
                    for account in result:
                        account_data = account.get("account", {})
                        parsed_data = account_data.get("data", {}).get("parsed", {})
                        info = parsed_data.get("info", {})
                        
                        amount = float(info.get("tokenAmount", {}).get("amount", 0))
                        if amount > 0:
                            holders_data.append({
                                "address": account.get("pubkey", ""),
                                "amount": amount
                            })
                    
                    total_holders = len(holders_data)
                    
                    if total_holders > 0:
                        # Trier par montant décroissant
                        holders_data.sort(key=lambda x: x["amount"], reverse=True)
                        
                        # Calculer la part des 10 plus gros holders
                        top_10 = holders_data[:10]
                        total_supply = sum(holder["amount"] for holder in holders_data)
                        top_10_amount = sum(holder["amount"] for holder in top_10)
                        
                        top_10_share = (top_10_amount / total_supply) * 100 if total_supply > 0 else 0
                        
                        return {
                            "holders": total_holders,
                            "top_10_share": round(top_10_share, 2)
                        }
        except Exception as e:
            logger.error(f"Erreur fallback holders: {e}")
        
        return {"holders": 0, "top_10_share": 0}
    
    async def get_holders_info_solscan_alternative(self, mint: str) -> Dict[str, Any]:
        """Alternative avec Solscan mais avec headers améliorés"""
        try:
            url = f"https://api.solscan.io/token/holders?token={mint}&size=100"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://solscan.io/",
                "Origin": "https://solscan.io"
            }
            
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Vérifier si les données sont dans le bon format
                    if isinstance(data, dict) and "data" in data:
                        holders_data = data["data"]
                    elif isinstance(data, list):
                        holders_data = data
                    else:
                        logger.warning(f"Format de données Solscan inattendu: {type(data)}")
                        return {"holders": 0, "top_10_share": 0}
                    
                    if holders_data:
                        total_holders = len(holders_data)
                        
                        # Calculer la part des 10 plus gros holders
                        top_10_share = 0
                        if total_holders > 0:
                            # Trier par montant décroissant
                            sorted_holders = sorted(holders_data, key=lambda x: float(x.get("amount", 0)), reverse=True)
                            top_10 = sorted_holders[:10]
                            
                            total_supply = sum(float(holder.get("amount", 0)) for holder in holders_data)
                            top_10_amount = sum(float(holder.get("amount", 0)) for holder in top_10)
                            
                            if total_supply > 0:
                                top_10_share = (top_10_amount / total_supply) * 100
                        
                        return {
                            "holders": total_holders,
                            "top_10_share": round(top_10_share, 2)
                        }
                else:
                    logger.warning(f"Solscan API returned status {response.status}")
        except Exception as e:
            logger.error(f"Erreur Solscan alternative: {e}")
        
        return {"holders": 0, "top_10_share": 0}
    
    async def get_holders_info(self, mint: str) -> Dict[str, Any]:
        """Récupère les informations sur les holders avec plusieurs méthodes de fallback"""
        # Essayer d'abord Helius
        holders_info = await self.get_holders_info_helius(mint)
        
        # Si Helius ne fonctionne pas, essayer Solscan avec headers améliorés
        if holders_info["holders"] == 0:
            holders_info = await self.get_holders_info_solscan_alternative(mint)
        
        # Si toujours pas de résultat, essayer la méthode de fallback
        if holders_info["holders"] == 0:
            holders_info = await self.get_holders_info_fallback(mint)
        
        return holders_info
    
    async def check_rug_pull_risk(self, mint: str) -> bool:
        """Vérifie le risque de rug-pull en analysant les autorités du token"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    mint,
                    {
                        "encoding": "jsonParsed"
                    }
                ]
            }
            
            async with self.session.post(SOLANA_RPC_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("result", {})
                    value = result.get("value", {})
                    
                    if value and value.get("data"):
                        parsed_data = value["data"].get("parsed", {})
                        info = parsed_data.get("info", {})
                        
                        # Vérifier si freezeAuthority est null (bon signe)
                        freeze_authority = info.get("freezeAuthority")
                        mint_authority = info.get("mintAuthority")
                        
                        # Risque élevé si les autorités sont toujours actives
                        has_freeze_authority = freeze_authority is not None
                        has_mint_authority = mint_authority is not None
                        
                        # Retourne True si il y a un risque (autorités actives)
                        return has_freeze_authority or has_mint_authority
        except Exception as e:
            logger.error(f"Erreur vérification rug-pull: {e}")
        
        return False  # En cas d'erreur, on assume qu'il n'y a pas de risque
    
    def calculate_market_cap(self, price_usd: float, supply: int, decimals: int) -> float:
        """Calcule le market cap"""
        if supply == 0 or decimals < 0:
            return 0
        
        adjusted_supply = supply / (10 ** decimals)
        return price_usd * adjusted_supply
    
    def calculate_score(self, data: Dict[str, Any]) -> tuple[int, list]:
        """Calcule le score final sur 20 avec explication détaillée"""
        score = 0
        explanations = []
        
        # Pools (2 points)
        pools = data.get("pools", 0)
        if pools >= 5:
            score += 2
            explanations.append("🔢 **Pools** : +2/2 pts (5+ pools = excellente liquidité)")
        elif pools >= 2:
            score += 1
            explanations.append("🔢 **Pools** : +1/2 pts (2-4 pools = bonne liquidité)")
        else:
            explanations.append("🔢 **Pools** : +0/2 pts (< 2 pools = liquidité faible)")
        
        # Volume 24h (3 points)
        volume = data.get("volume_24h", 0)
        if volume >= 1000000:  # 1M+
            score += 3
            explanations.append("📊 **Volume 24h** : +3/3 pts (1M$+ = très actif)")
        elif volume >= 100000:  # 100K+
            score += 2
            explanations.append("📊 **Volume 24h** : +2/3 pts (100K$+ = actif)")
        elif volume >= 10000:  # 10K+
            score += 1
            explanations.append("📊 **Volume 24h** : +1/3 pts (10K$+ = peu actif)")
        else:
            explanations.append("📊 **Volume 24h** : +0/3 pts (< 10K$ = très peu actif)")
        
        # Liquidité (3 points)
        liquidity = data.get("liquidity", 0)
        if liquidity >= 1000000:  # 1M+
            score += 3
            explanations.append("💧 **Liquidité** : +3/3 pts (1M$+ = excellente)")
        elif liquidity >= 100000:  # 100K+
            score += 2
            explanations.append("💧 **Liquidité** : +2/3 pts (100K$+ = bonne)")
        elif liquidity >= 10000:  # 10K+
            score += 1
            explanations.append("💧 **Liquidité** : +1/3 pts (10K$+ = faible)")
        else:
            explanations.append("💧 **Liquidité** : +0/3 pts (< 10K$ = très faible)")
        
        # Variation de prix (2 points)
        price_change = abs(data.get("price_change_24h", 0))
        if price_change <= 5:  # Stabilité
            score += 2
            explanations.append("📈 **Stabilité** : +2/2 pts (±5% = très stable)")
        elif price_change <= 15:
            score += 1
            explanations.append("📈 **Stabilité** : +1/2 pts (±15% = modérément stable)")
        else:
            explanations.append("📈 **Stabilité** : +0/2 pts (>15% = très volatil)")
        
        # Market cap (3 points)
        market_cap = data.get("market_cap", 0)
        if market_cap >= 10000000:  # 10M+
            score += 3
            explanations.append("🏦 **Market Cap** : +3/3 pts (10M$+ = large cap)")
        elif market_cap >= 1000000:  # 1M+
            score += 2
            explanations.append("🏦 **Market Cap** : +2/3 pts (1M$+ = mid cap)")
        elif market_cap >= 100000:  # 100K+
            score += 1
            explanations.append("🏦 **Market Cap** : +1/3 pts (100K$+ = small cap)")
        else:
            explanations.append("🏦 **Market Cap** : +0/3 pts (< 100K$ = micro cap)")
        
        # Holders (3 points)
        holders = data.get("holders", 0)
        if holders >= 10000:
            score += 3
            explanations.append("👥 **Holders** : +3/3 pts (10K+ = très adopté)")
        elif holders >= 1000:
            score += 2
            explanations.append("👥 **Holders** : +2/3 pts (1K+ = bien adopté)")
        elif holders >= 100:
            score += 1
            explanations.append("👥 **Holders** : +1/3 pts (100+ = peu adopté)")
        else:
            explanations.append("👥 **Holders** : +0/3 pts (< 100 = très peu adopté)")
        
        # Top 10 share (2 points) - Plus c'est bas, mieux c'est
        top_10_share = data.get("top_10_share", 100)
        if top_10_share <= 20:
            score += 2
            explanations.append("🧮 **Distribution** : +2/2 pts (≤20% = très décentralisé)")
        elif top_10_share <= 50:
            score += 1
            explanations.append("🧮 **Distribution** : +1/2 pts (≤50% = moyennement décentralisé)")
        else:
            explanations.append("🧮 **Distribution** : +0/2 pts (>50% = très centralisé)")
        
        # Rug-pull (2 points)
        if not data.get("rug_pull_risk", True):
            score += 2
            explanations.append("🚨 **Sécurité** : +2/2 pts (autorités révoquées = sécurisé)")
        else:
            explanations.append("🚨 **Sécurité** : +0/2 pts (autorités actives = risque élevé)")
        
        return min(score, 20), explanations  # Maximum 20 points
    
    def format_number(self, num: float) -> str:
        """Formate les nombres pour l'affichage"""
        if num >= 1_000_000_000:
            return f"{num / 1_000_000_000:.2f}B"
        elif num >= 1_000_000:
            return f"{num / 1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.2f}K"
        else:
            return f"{num:.2f}"
    
    async def analyze_token(self, mint: str) -> Dict[str, Any]:
        """Analyse complète d'un token"""
        if not self.is_valid_mint(mint):
            return {"error": "Mint address invalide"}
        
        try:
            # Récupération des données en parallèle
            dex_data, metadata, supply_info, holders_info = await asyncio.gather(
                self.get_dexscreener_data(mint),
                self.get_token_metadata(mint),
                self.get_token_supply_info(mint),
                self.get_holders_info(mint),
                return_exceptions=True
            )
            
            # Vérification du risque de rug-pull
            rug_pull_risk = await self.check_rug_pull_risk(mint)
            
            # Fusion des données de supply (priorité aux données RPC)
            supply = supply_info.get("supply", 0) or metadata.get("supply", 0)
            decimals = supply_info.get("decimals", 0) or metadata.get("decimals", 0)
            
            # Calcul du market cap
            market_cap = self.calculate_market_cap(
                dex_data.get("price_usd", 0),
                supply,
                decimals
            )
            
            # Compilation des données
            analysis_data = {
                "mint": mint,
                "name": metadata.get("name", "Unknown"),
                "symbol": metadata.get("symbol", "Unknown"),
                "created_at": metadata.get("created_at"),
                "pools": dex_data.get("pools", 0),
                "liquidity": dex_data.get("liquidity", 0),
                "volume_24h": dex_data.get("volume_24h", 0),
                "price_usd": dex_data.get("price_usd", 0),
                "price_change_24h": dex_data.get("price_change_24h", 0),
                "market_cap": market_cap,
                "supply": supply,
                "decimals": decimals,
                "holders": holders_info.get("holders", 0),
                "top_10_share": holders_info.get("top_10_share", 0),
                "rug_pull_risk": rug_pull_risk
            }
            
            # Calcul du score
            score, explanations = self.calculate_score(analysis_data)
            analysis_data["score"] = score
            analysis_data["explanations"] = explanations
            
            # Log pour debug
            logger.info(f"Holders info pour {mint}: {holders_info}")
            
            return analysis_data
            
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse: {e}")
            return {"error": f"Erreur lors de l'analyse: {str(e)}"}
    
    def format_analysis_message(self, data: Dict[str, Any]) -> str:
        """Formate le message d'analyse"""
        if "error" in data:
            return f"❌ **Erreur**: {data['error']}"
        
        # Formatage des données
        name = data.get("name", "Unknown")
        symbol = data.get("symbol", "Unknown")
        mint = data.get("mint", "")
        created_at = data.get("created_at", "Inconnue")
        
        if created_at and created_at != "Inconnue":
            created_at = created_at.split("T")[0]  # Garde seulement la date
        
        pools = data.get("pools", 0)
        liquidity = self.format_number(data.get("liquidity", 0))
        volume_24h = self.format_number(data.get("volume_24h", 0))
        price_usd = data.get("price_usd", 0)
        price_change_24h = data.get("price_change_24h", 0)
        market_cap = self.format_number(data.get("market_cap", 0))
        supply = data.get("supply", 0)
        decimals = data.get("decimals", 0)
        holders = data.get("holders", 0)
        top_10_share = data.get("top_10_share", 0)
        rug_pull_risk = data.get("rug_pull_risk", False)
        score = data.get("score", 0)
        explanations = data.get("explanations", [])
        
        # Formatage de la supply
        if supply > 0 and decimals > 0:
            formatted_supply = f"{supply / (10 ** decimals):,.0f}"
        else:
            formatted_supply = f"{supply:,}"
        
        # Indicateur de changement de prix
        price_indicator = "📈" if price_change_24h >= 0 else "📉"
        
        # Indicateur de rug-pull
        rug_indicator = "🚨 Oui" if rug_pull_risk else "✅ Non"
        
        # Évaluation du score
        if score >= 16:
            score_emoji = "🟢"
            score_eval = "Excellent"
        elif score >= 12:
            score_emoji = "🟡"
            score_eval = "Bon"
        elif score >= 8:
            score_emoji = "🟠"
            score_eval = "Moyen"
        else:
            score_emoji = "🔴"
            score_eval = "Risqué"
        
        # Message principal
        message = f"""💡 *Analyse Solana* — `{symbol}` ({name})
🏷️ Mint           : `{mint}`
🗓️ Créé le       : {created_at}
🔢 Pools actives  : {pools}
💧 Liquidité      : ${liquidity}
📊 Volume 24h    : ${volume_24h}
💲 Prix (USD)    : ${price_usd:.6f}
{price_indicator} Δ24h          : {price_change_24h:.2f}%
🏦 Market Cap     : ${market_cap}
🔢 Supply        : {formatted_supply} (decimals={decimals})
👥 Holders       : {holders:,}
🧮 Top 10 share   : {top_10_share:.1f}%
🚨 Rug-pull      : {rug_indicator}

{score_emoji} *Score final* : {score}/20 ({score_eval})

📝 **Détail du scoring :**
"""
        
        # Ajout des explications
        for explanation in explanations:
            message += f"{explanation}\n"
        
        # Conseil basé sur le score
        if score >= 16:
            message += "\n💡 **Recommandation** : Token de qualité avec de bonnes métriques"
        elif score >= 12:
            message += "\n💡 **Recommandation** : Token correct, surveiller l'évolution"
        elif score >= 8:
            message += "\n⚠️ **Attention** : Métriques moyennes, investir avec prudence"
        else:
            message += "\n🚨 **Alerte** : Métriques faibles, risque élevé"
        
        return message

# Bot Telegram
class TelegramBot:
    def __init__(self):
        self.analyzer = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Commande /start"""
        welcome_message = """🚀 **Bot d'Analyse Solana**

Bienvenue ! Ce bot vous permet d'analyser les tokens Solana.

**Commandes disponibles:**
• `/analyse <mint_address>` - Analyse un token
• `/help` - Affiche cette aide

**Exemple:**
`/analyse EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

Envoyez un mint address pour commencer l'analyse !"""
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Commande /help"""
        help_message = """📚 **Aide - Bot d'Analyse Solana**

**Comment utiliser le bot:**
1. Envoyez `/analyse` suivi d'un mint address
2. Le bot analysera le token et vous donnera:
   • Informations générales (nom, symbole, date de création)
   • Métriques de trading (prix, volume, liquidité)
   • Données de tokenomics (supply, holders, distribution)
   • Score de risque et évaluation

**Exemple d'utilisation:**
`/analyse EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

**Le score est calculé sur 20 points selon:**
• Nombre de pools de liquidité
• Volume de trading 24h
• Liquidité totale
• Stabilité du prix
• Market cap
• Nombre de holders
• Distribution des tokens
• Risque de rug-pull"""
        
        await update.message.reply_text(help_message, parse_mode='Markdown')
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Commande /analyse"""
        if not context.args:
            await update.message.reply_text(
                "❌ **Erreur**: Veuillez fournir un mint address.\n\n"
                "**Exemple:** `/analyse EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`",
                parse_mode='Markdown'
            )
            return
        
        mint = context.args[0]
        
        # Message de chargement
        loading_message = await update.message.reply_text(
            "🔄 **Analyse en cours...**\n\n"
            "📊 Récupération des données de trading...\n"
            "🏦 Analyse des métriques financières...\n"
            "👥 Calcul de la distribution des holders...\n"
            "🔍 Vérification du risque de rug-pull...",
            parse_mode='Markdown'
        )
        
        try:
            async with SolanaAnalyzer() as analyzer:
                analysis = await analyzer.analyze_token(mint)
                formatted_message = analyzer.format_analysis_message(analysis)
                
                # Mise à jour du message
                await loading_message.edit_text(formatted_message, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse: {e}")
            await loading_message.edit_text(
                f"❌ **Erreur**: Une erreur s'est produite lors de l'analyse.\n\n"
                f"**Détails**: {str(e)[:200]}...",
                parse_mode='Markdown'
            )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gère les messages texte (mint addresses)"""
        message_text = update.message.text.strip()
        
        # Vérifie si c'est potentiellement un mint address
        if len(message_text) >= 32 and len(message_text) <= 44:
            try:
                base58.b58decode(message_text)
                # C'est un mint address valide, on lance l'analyse
                context.args = [message_text]
                await self.analyze_command(update, context)
                return
            except:
                pass
        
        # Message par défaut
        await update.message.reply_text(
            "❓ **Message non reconnu**\n\n"
            "Envoyez `/analyse <mint_address>` pour analyser un token.\n"
            "Ou envoyez `/help` pour plus d'informations.",
            parse_mode='Markdown'
        )

def main():
    """Fonction principale"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        logger.error("TELEGRAM_BOT_TOKEN n'est pas configuré")
        return
    
    if not HELIUS_API_KEY or HELIUS_API_KEY == "your_helius_api_key_here":
        logger.warning("HELIUS_API_KEY n'est pas configuré, certaines fonctionnalités peuvent être limitées")
    
    # Création du bot
    bot = TelegramBot()
    
    # Configuration de l'application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Ajout des handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("analyse", bot.analyze_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    # Démarrage du bot
    logger.info("Bot démarré...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
