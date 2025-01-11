#!/usr/bin/env python3
import json
import subprocess
import sys
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pyudev

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/sway-monitor-daemon.log'),
        logging.StreamHandler()
    ]
)

PROFILES_PATH = Path.home() / '.config' / 'sway-monitor-profiles'
ACTIVE_PROFILE = PROFILES_PATH / 'active_profile'
DEFAULT_PROFILE = 'default'

class MonitorProfile:
    def __init__(self, name: str, configs: Dict = None):
        self.name = name
        self.configs = configs or {}
        self.file_path = PROFILES_PATH / f"{name}.json"

    def save(self):
        """Save profile to file"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, 'w') as f:
            json.dump(self.configs, f, indent=2)

    @classmethod
    def load(cls, name: str) -> 'MonitorProfile':
        """Load profile from file"""
        file_path = PROFILES_PATH / f"{name}.json"
        if file_path.exists():
            with open(file_path, 'r') as f:
                configs = json.load(f)
            return cls(name, configs)
        return cls(name)

class MonitorDaemon:
    def __init__(self):
        self.profiles: Dict[str, MonitorProfile] = {}
        self.active_profile_name = DEFAULT_PROFILE
        self.current_monitors = set()
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by('drm')  # Monitor DRM (Direct Rendering Manager) devices

    def load_profiles(self):
        """Load all profiles from the profiles directory"""
        PROFILES_PATH.mkdir(parents=True, exist_ok=True)
        for profile_file in PROFILES_PATH.glob('*.json'):
            profile_name = profile_file.stem
            self.profiles[profile_name] = MonitorProfile.load(profile_name)
        
        # Ensure default profile exists
        if DEFAULT_PROFILE not in self.profiles:
            self.profiles[DEFAULT_PROFILE] = MonitorProfile(DEFAULT_PROFILE)

        # Load active profile
        if ACTIVE_PROFILE.exists():
            with open(ACTIVE_PROFILE, 'r') as f:
                self.active_profile_name = f.read().strip()

    def save_active_profile(self):
        """Save current active profile name"""
        with open(ACTIVE_PROFILE, 'w') as f:
            f.write(self.active_profile_name)

    def get_current_monitors(self) -> List[dict]:
        """Get current monitor configuration from sway"""
        try:
            output = subprocess.check_output(
                ['swaymsg', '-t', 'get_outputs'], 
                universal_newlines=True
            )
            return json.loads(output)
        except subprocess.CalledProcessError:
            return []

    def find_best_config(self, monitor: dict) -> Optional[dict]:
        """Find best matching configuration for a monitor"""
        model = monitor.get('model', '')
        name = monitor.get('name', '')
        serial = monitor.get('serial', '')

        # First try exact matches in active profile
        active_profile = self.profiles[self.active_profile_name]
        for identifier in [f"{model}_{serial}", model, name]:
            if identifier in active_profile.configs:
                return active_profile.configs[identifier]

        # Then try other profiles
        for profile in self.profiles.values():
            for identifier in [f"{model}_{serial}", model, name]:
                if identifier in profile.configs:
                    return profile.configs[identifier]

        # Return None if no match found
        return None

    def apply_monitor_config(self, monitor: dict, config: dict):
        """Apply configuration to a monitor"""
        cmd = ['swaymsg', 'output', monitor['name']]
        
        if config.get('enabled', True):
            width, height = config['resolution'].split('x')
            x, y = config['position'].split(',')
            
            cmd.extend(['pos', x, y])
            cmd.extend(['res', width, height])
            cmd.extend(['scale', str(config['scale'])])
            cmd.extend(['transform', config['transform']])
        else:
            cmd.append('disable')

        try:
            subprocess.run(cmd, check=True)
            logging.info(f"Applied config to monitor {monitor['name']}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error applying config to {monitor['name']}: {e}")
            return False

    def update_monitor_configs(self):
        """Update configurations for all connected monitors"""
        monitors = self.get_current_monitors()
        new_monitor_set = {m['name'] for m in monitors}

        # Check for changes in monitor setup
        if new_monitor_set != self.current_monitors:
            logging.info("Monitor configuration changed")
            logging.info(f"Previous monitors: {self.current_monitors}")
            logging.info(f"Current monitors: {new_monitor_set}")

            # Apply configurations
            for monitor in monitors:
                config = self.find_best_config(monitor)
                if config:
                    self.apply_monitor_config(monitor, config)
                else:
                    logging.warning(f"No configuration found for monitor {monitor['name']}")

            self.current_monitors = new_monitor_set

    def save_current_setup(self, profile_name: Optional[str] = None):
        """Save current monitor setup to a profile"""
        if profile_name:
            self.active_profile_name = profile_name
        
        monitors = self.get_current_monitors()
        profile = self.profiles.get(self.active_profile_name)
        if not profile:
            profile = MonitorProfile(self.active_profile_name)
            self.profiles[self.active_profile_name] = profile

        for monitor in monitors:
            model = monitor.get('model', '')
            if not model:
                continue

            config = {
                'model': model,
                'position': f"{monitor['rect']['x']},{monitor['rect']['y']}",
                'resolution': f"{monitor['current_mode']['width']}x{monitor['current_mode']['height']}",
                'scale': monitor.get('scale', 1.0),
                'transform': monitor.get('transform', 'normal'),
                'enabled': not monitor.get('disabled', False)
            }
            
            # Save with both model and model_serial identifiers
            profile.configs[model] = config
            if monitor.get('serial'):
                profile.configs[f"{model}_{monitor['serial']}"] = config

        profile.save()
        self.save_active_profile()
        logging.info(f"Saved current setup to profile: {self.active_profile_name}")

    def run(self):
        """Main daemon loop"""
        self.load_profiles()

        # Start monitoring
        observer = pyudev.MonitorObserver(self.monitor, self.handle_udev_event)
        observer.start()

        try:
            # Initial configuration
            self.update_monitor_configs()
            
            # Keep the daemon running
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()

    def handle_udev_event(self, action, device):
        """Handle udev events for monitor changes"""
        if action in ['add', 'remove']:
            logging.info(f"Monitor {action} event detected")
            time.sleep(2)  # Wait for system to recognize the change
            self.update_monitor_configs()

if __name__ == '__main__':
    daemon = MonitorDaemon()
    daemon.run()