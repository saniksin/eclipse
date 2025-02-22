from tasks.orca_swap import OrcaSwap
from tasks.solar import SolarSwap

possible_router = {
    'ORCA': OrcaSwap,
    'SOLAR': SolarSwap,
}