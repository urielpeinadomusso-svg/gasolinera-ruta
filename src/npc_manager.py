# ----------------------------------------
"""
NPC Manager - Gasolinera Ruta
Generado por: Gemini 1.5 Pro (IA #005)
Fecha: [HOY]
Versión: 1.0

Responsabilidades:
- Carga/descarga dinámica de NPCs desde JSON
- Algoritmo de spawn basado en día y probabilidades
- Actualización de estado emocional
- Detección de muerte/desaparición de NPCs
- Persistencia automática

Uso:
    manager = NPCManager(data_path="game/data/npcs/")
    npc = manager.get_npc_for_day(current_day)
    manager.update_npc_emotion(npc_id, delta=+1)
"""

# python/npc_manager.py
# version: 1.0.0
# date: 2026-03-09
# @author: @urielpeinadomusso

"""
Gestor Avanzado de NPCs para Ren'Py
Optimizado para CPUs antiguas (Intel i5 4th Gen) y 8GB RAM.
Maneja 90 NPCs a través de 3000 días simulados usando Lazy Loading y LRU Caching.
"""

import json
import os
import random
import logging
from typing import Dict, List, Optional, Any
from collections import OrderedDict

# ==========================================
# CONFIGURACIÓN DE LOGGING
# ==========================================
logger = logging.getLogger("NPC_Manager")
logger.setLevel(logging.DEBUG)
# En Ren'Py los prints van a la consola o log.txt, pero forzamos un file handler
fh = logging.FileHandler("npc_system_debug.log", encoding="utf-8")
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

# ==========================================
# CLASES DE DATOS (Optimizadas con __slots__)
# ==========================================
class NPC:
    """
    Representación ligera de un NPC.
    Usa __slots__ para reducir drásticamente el consumo de RAM, 
    evitando la creación del diccionario __dict__ por instancia.
    """
    __slots__ = [
        'id', 'name', 'is_alive', 'location', 'schedule', 
        'trust', 'mood', 'death_reason'
    ]

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get('id', 'unknown')
        self.name: str = data.get('name', 'Desconocido')
        self.is_alive: bool = data.get('is_alive', True)
        self.location: str = data.get('location', 'home')
        self.schedule: Dict[str, str] = data.get('schedule', {})
        self.trust: int = data.get('trust', 0)
        self.mood: str = data.get('mood', 'neutral')
        self.death_reason: Optional[str] = data.get('death_reason', None)

    def to_dict(self) -> Dict[str, Any]:
        """Serializa el objeto de vuelta a diccionario para JSON."""
        return {
            'id': self.id,
            'name': self.name,
            'is_alive': self.is_alive,
            'location': self.location,
            'schedule': self.schedule,
            'trust': self.trust,
            'mood': self.mood,
            'death_reason': self.death_reason
        }

# ==========================================
# GESTOR PRINCIPAL
# ==========================================
class NPCManager:
    def __init__(self, data_path: str = "game/data/npcs/npc_instances.json"):
        self.data_path = data_path
        
        # Max NPCs activos en memoria al mismo tiempo (Evita saturar RAM)
        self.MAX_LOADED_NPCS = 15
        
        # Pool LRU (Least Recently Used) para instanciación Lazy
        self._npc_pool: OrderedDict[str, NPC] = OrderedDict()
        
        # Datos crudos cargados del JSON (consumen muy poca RAM al ser dicts básicos)
        self._raw_data: Dict[str, Dict[str, Any]] = {}
        
        # Índices ligeros para búsquedas O(1) en el spawn
        self._alive_index: set = set()
        
        self.load_database()

    def load_database(self) -> None:
        """Carga el archivo JSON y construye los índices ligeros."""
        if not os.path.exists(self.data_path):
            logger.error(f"Archivo no encontrado: {self.data_path}. Se requiere inicializar.")
            return

        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Construir índices
            for npc_data in data.get('npcs', []):
                npc_id = npc_data['id']
                self._raw_data[npc_id] = npc_data
                
                if npc_data.get('is_alive', True):
                    self._alive_index.add(npc_id)
                    
            logger.info(f"Base de datos cargada. {len(self._raw_data)} NPCs totales, {len(self._alive_index)} vivos.")
            
        except json.JSONDecodeError as e:
            logger.critical(f"JSON corrupto en {self.data_path}: {e}")
            # Aquí podrías implementar carga de un archivo .bak
        except Exception as e:
            logger.critical(f"Error inesperado al cargar la base de datos: {e}")

    def get_npc(self, npc_id: str) -> Optional[NPC]:
        """
        Obtiene un NPC usando Lazy Loading y LRU Cache.
        Si no está en memoria, lo instancia desde _raw_data.
        Si la memoria está llena, expulsa al más antiguo.
        """
        if npc_id not in self._raw_data:
            logger.warning(f"Intento de cargar NPC inexistente: {npc_id}")
            return None

        # Si ya está en el pool, lo movemos al final (más recientemente usado)
        if npc_id in self._npc_pool:
            self._npc_pool.move_to_end(npc_id)
            return self._npc_pool[npc_id]

        # Si el pool está lleno, expulsamos al menos usado (el primero)
        if len(self._npc_pool) >= self.MAX_LOADED_NPCS:
            evicted_id, evicted_npc = self._npc_pool.popitem(last=False)
            # Guardamos sus cambios en _raw_data antes de sacarlo de memoria
            self._raw_data[evicted_id] = evicted_npc.to_dict()
            logger.debug(f"NPC expulsado de RAM (LRU): {evicted_id}")

        # Instanciar y agregar al pool
        npc = NPC(self._raw_data[npc_id])
        self._npc_pool[npc_id] = npc
        logger.debug(f"NPC cargado en RAM: {npc_id}")
        return npc

    def spawn_npcs(self, day: int, location: str, time_of_day: str, max_spawns: int = 5) -> List[str]:
        """
        Algoritmo de Spawn optimizado para CPU.
        Decide quién aparece hoy en la ubicación dada.
        Retorna solo los IDs (strings) para no cargar los objetos a menos que el jugador interactúe.
        """
        potential_spawns = []
        
        # Iterar solo sobre NPCs vivos (búsqueda rápida)
        for npc_id in self._alive_index:
            npc_raw = self._raw_data[npc_id]
            
            # Verificar si su horario coincide
            scheduled_loc = npc_raw.get('schedule', {}).get(time_of_day)
            
            if scheduled_loc == location:
                # 80% de probabilidad de que cumplan su rutina (añade variabilidad)
                if random.random() < 0.8:
                    potential_spawns.append(npc_id)

        # Si hay más NPCs de los permitidos, seleccionamos aleatoriamente
        if len(potential_spawns) > max_spawns:
            # Usamos random.sample que está implementado en C y es muy rápido
            spawned = random.sample(potential_spawns, max_spawns)
        else:
            spawned = potential_spawns
            
        logger.info(f"Día {day}, {time_of_day} en {location}: Spawneados {len(spawned)} NPCs.")
        return spawned

    def update_interaction(self, npc_id: str, trust_change: int, new_mood: str) -> None:
        """
        Actualiza el estado emocional tras una interacción.
        Comprueba la condición de muerte por "disgusto".
        """
        npc = self.get_npc(npc_id)
        if not npc or not npc.is_alive:
            return

        npc.trust += trust_change
        npc.mood = new_mood
        
        # Límite duro de confianza
        npc.trust = max(-100, min(100, npc.trust))

        logger.debug(f"Interacción con {npc_id}: Trust cambiado a {npc.trust}, Mood: {new_mood}")

        # Lógica de "Muerte" social (El NPC abandona la ciudad por odiar al prota)
        if npc.trust <= -80:
            self._kill_npc(npc_id, reason="disgusto_extremo")

    def process_daily_events(self, day: int) -> None:
        """
        Procesa eventos pasivos al terminar el día.
        Ejemplo: Probabilidad minúscula de accidentes aleatorios (muerte).
        Debe llamarse una vez por noche en el script de Ren'Py.
        """
        # Convertimos a lista para evitar RuntimeError por mutar un set iterándolo
        for npc_id in list(self._alive_index):
            
            # Chance de accidente: 0.05% por día por NPC (ajustar según balance)
            if random.random() < 0.0005:
                self._kill_npc(npc_id, reason="accidente_tragico")
                logger.info(f"EVENTO DÍA {day}: {npc_id} falleció en un accidente.")

    def _kill_npc(self, npc_id: str, reason: str) -> None:
        """Marca un NPC como no disponible permanentemente y limpia índices."""
        npc = self.get_npc(npc_id)
        if not npc:
            return

        npc.is_alive = False
        npc.death_reason = reason
        
        # Eliminar del índice de vivos
        if npc_id in self._alive_index:
            self._alive_index.remove(npc_id)
            
        logger.warning(f"NPC {npc_id} HA SIDO ELIMINADO de la simulación. Razón: {reason}")

    def save_state(self) -> bool:
        """
        Guarda el estado actual al JSON.
        Implementa "Atomic Saving" para evitar corrupción si el juego crashea.
        """
        # 1. Sincronizar NPCs activos en el pool hacia los datos crudos
        for npc_id, npc in self._npc_pool.items():
            self._raw_data[npc_id] = npc.to_dict()

        # 2. Preparar el diccionario final
        export_data = {
            "npcs": list(self._raw_data.values())
        }

        temp_path = self.data_path + ".tmp"
        target_dir = os.path.dirname(self.data_path)
        if target_dir:
            # Aseguramos que la ruta exista para evitar errores al guardar por primera vez
            os.makedirs(target_dir, exist_ok=True)
        
        try:
            # 3. Escribir primero en un archivo temporal (Atomic Save)
            # Usamos separators compactos para reducir tamaño y estrés de I/O
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, separators=(',', ':'))
            
            # 4. Reemplazar el archivo original con el temporal de forma segura
            os.replace(temp_path, self.data_path)
            logger.info("Guardado de NPCs completado exitosamente.")
            return True
            
        except Exception as e:
            logger.error(f"Error crítico al guardar NPCs: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False

# ==========================================
# CÓMO USAR EN REN'PY (Ejemplo rápido)
# ==========================================
"""
init python:
    from python.npc_manager import NPCManager
    npc_sys = NPCManager(data_path=renpy.config.savedir + "/npc_instances.json")

label location_cafe:
    # 1. Obtener quién está aquí (rápido, no satura RAM)
    $ npcs_presentes = npc_sys.spawn_npcs(current_day, "cafe_central", "afternoon")
    
    # 2. Mostrar opciones al jugador...
    
    # 3. Si el jugador elige hablar con "npc_005":
    $ npc_actual = npc_sys.get_npc("npc_005") # <- Carga perezosa aquí
    
    # 4. Actualizar después de hablar
    $ npc_sys.update_interaction("npc_005", trust_change=-5, new_mood="angry")
    
    # 5. Al final del día
    $ npc_sys.process_daily_events(current_day)
    $ npc_sys.save_state()
"""
