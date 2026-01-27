"""
Module de gestion du timing pour la boucle principale.
Gère les horaires de trading et le calcul des temps d'attente.
"""

import asyncio
import sys
from datetime import datetime, time as dt_time, timedelta


# Horaires de trading
EVENING_CUTOFF = dt_time(22, 30)  # 22h30
MORNING_START = dt_time(15, 0)     # 15h00

# Temps d'attente par défaut (en secondes)
DEFAULT_WAIT_TIME = 600
OFF_HOURS_WAIT_TIME = 3600


def is_trading_hours(current_time: dt_time = None) -> bool:
    """
    Vérifie si on est dans les heures de trading (15h00 - 22h30).
    
    Args:
        current_time: L'heure à vérifier. Si None, utilise l'heure actuelle.
    
    Returns:
        True si on est dans les heures de trading, False sinon.
    """
    if current_time is None:
        current_time = datetime.now().time()
    
    return MORNING_START <= current_time < EVENING_CUTOFF


def get_wait_time(time_before_next_run: int) -> int:
    """
    Calcule le temps d'attente avant le prochain appel en tenant compte
    des heures de trading.
    
    - Entre 22h30 et 15h00 : attente de 1 heure (ou jusqu'à 15h00)
    - Entre 15h00 et 22h30 : utilise le temps demandé (ou jusqu'à 22h30)
    
    Args:
        time_before_next_run: Temps d'attente souhaité en secondes.
    
    Returns:
        Temps d'attente ajusté en secondes.
    """
    now = datetime.now()
    current_time = now.time()
    
    if not is_trading_hours(current_time):
        # Hors heures de trading
        next_call = now + timedelta(seconds=OFF_HOURS_WAIT_TIME)
        
        if current_time < MORNING_START:
            # Avant 15h00 - vérifier si on peut attendre jusqu'à 15h00
            target_15h = datetime.combine(now.date(), MORNING_START)
            if next_call > target_15h:
                wait_seconds = (target_15h - now).total_seconds()
                return max(60, int(wait_seconds))
        
        return OFF_HOURS_WAIT_TIME
    else:
        # Pendant les heures de trading
        next_call = now + timedelta(seconds=time_before_next_run)
        target_22h30 = datetime.combine(now.date(), EVENING_CUTOFF)
        
        if next_call.time() > EVENING_CUTOFF:
            # Le prochain appel dépasserait 22h30
            wait_seconds = (target_22h30 - now).total_seconds()
            return max(60, int(wait_seconds))
        
        return time_before_next_run


async def countdown_display(wait_seconds: int) -> None:
    """
    Affiche un compte à rebours dans la console.
    
    Args:
        wait_seconds: Nombre de secondes à attendre.
    """
    current_hour = datetime.now().strftime("%H:%M")
    remaining = wait_seconds
    
    while remaining > 0:
        mins, secs = divmod(remaining, 60)
        status_msg = f"\r⏳ {current_hour} - Prochain appel dans {int(mins):02d}:{int(secs):02d}  "
        sys.stdout.write(status_msg)
        sys.stdout.flush()
        
        await asyncio.sleep(1)
        remaining -= 1
    
    # Nouvelle ligne après le compte à rebours
    print()
