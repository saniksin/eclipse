import inquirer
from termcolor import colored
from inquirer.themes import load_theme_from_dict as loadth


def get_action() -> str:
    """Пользователь выбирает действие через меню"""

    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "action",
            message=colored('Выберите ваше действие', 'light_yellow'),
            choices=[
                'Import data to db',
                'Bridge',
                'Swap',
                'TurboTap',
                'Lending',
                'Accept Eclipse Invite (Discord)',
                'Exit'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['action']


def swap_menu_token() -> str:
    """Меню для ORCA Swap"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "orca_swap_action",
            message=colored('Выберите действие для Swap', 'light_yellow'),
            choices=[
                'Swap native to token',
                'Swap token to native',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['orca_swap_action']

def lending_menu() -> str:
    """Меню для Lending"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "orca_swap_action",
            message=colored('Выберите действие для Lending', 'light_yellow'),
            choices=[
                'Astrol',
                'SaveFinance',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['orca_swap_action']

def astrol_menu() -> str:
    """Меню для Astrol Lending"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "orca_swap_action",
            message=colored('Выберите действие для Astrol', 'light_yellow'),
            choices=[
                'Deposit USDC',
                'Withdraw USDC',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['orca_swap_action']

def save_menu() -> str:
    """Меню для Safe Finance Lending"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "orca_swap_action",
            message=colored('Выберите действие для Save Finance', 'light_yellow'),
            choices=[
                'Deposit ETH',
                'Withdraw ETH',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['orca_swap_action']

def bridge_menu() -> str:
    """Меню для Bridge"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "swap_action",
            message=colored('Выберите действие для Bridge', 'light_yellow'),
            choices=[
                'Relay',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['swap_action']


def tap_menu() -> str:
    """Меню для TAP"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "swap_action",
            message=colored('Выберите действие для Tap', 'light_yellow'),
            choices=[
                'TurboTap (Tap)',
                'TurboTap (Registrations)',
                'TurboTap (ParseStats)',
                'TurboTap (ParseRefCodes)',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['swap_action']


def swap_menu() -> str:
    """Меню для Swap"""
    theme = {
        'Question': {
            'brackets_color': 'bright_yellow'
        },
        'List': {
            'selection_color': 'bright_blue'
        },
    }

    question = [
        inquirer.List(
            "swap_action",
            message=colored('Выберите действие для Swap', 'light_yellow'),
            choices=[
                'ORCA',
                'SOLAR',
                'MIX (SOLAR, ORCA...)',
                'Go back'
            ]
        )
    ]

    return inquirer.prompt(question, theme=loadth(theme))['swap_action']
