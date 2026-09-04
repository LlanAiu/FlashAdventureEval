import argparse
import json
import os
import time

from agent import SeekerBot, MapperBot, SolverBot
from tools import load_config


def load_game_metadata(games_path="./json/game_prompt.json") -> dict:
    if not os.path.exists(games_path):
        raise FileNotFoundError(f"⚠️ The file '{games_path}' does not exist.")
    with open(games_path, "r", encoding="utf-8") as f:
        return json.load(f)


def choose_game(game_dict: dict) -> str:
    game_list = list(game_dict.keys())
    print("\n🎮 Available Games:")
    for idx, name in enumerate(game_list, 1):
        print(f"{idx}. {name}")
    while True:
        try:
            choice = int(input("\nSelect a game by number: "))
            if 1 <= choice <= len(game_list):
                return game_list[choice - 1]
        except ValueError:
            pass
        print("❌ Invalid input. Try again.")


def run_clue_seeker(config_path, game_name):
    seeker = SeekerBot(config_path=config_path, game_name=game_name)
    print("\n🕵️ Running ClueSeeker...")

    count = seeker.run()
    if count == 0:
        print("🛑 No more actions taken. Possibly reached action limit.")
    print(f"✅ ClueSeeker completed with {count} actions.\n")
    return count


def run_mapper(config_path, game_name):
    print("🔗 Running MapperBot...")
    mapper = MapperBot(config_path=config_path, game_name=game_name)
    result = mapper.run()
    print("✅ Mapper completed.\n")
    return mapper.memory_path


def load_mapping_data(mapping_path):
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                print("[⚠️] The format of mapping.json is not a list!")
                return []
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        print('⚠️ An error occurred while loading the mapping file')
        return []


def run_solver(config_path, game_name, failed_mappings, total_actions, max_actions):
    
    if not failed_mappings:
        print("🎉 All mappings successful. No need for Solver.")
        return 0

    print(f"🧠 Running SolverBot for {len(failed_mappings)} failed mappings...")
    solver_total = 0

    for idx, single_mapping in enumerate(failed_mappings):
        clue = single_mapping.get("clue", {})
        related_memory = single_mapping.get("related_memory", "(no memory)")
        expected_action = single_mapping.get("expected_action", "(no action)")

        print(f"\n📝 Processing mapping [{idx + 1}/{len(failed_mappings)}]")
        print("🔍 Clue:")
        for key, value in clue.items():
            print(f"   • {key}: {value}")
        print(f"🧠 Memory     : {related_memory}")
        print(f"🎯 Expected   : {expected_action}")

        solver = SolverBot(config_path, game_name)
        solver.get_mapping([single_mapping])  # Pass the entire mapping object
        solver_actions = solver.run()
        solver_total += solver_actions
        total_actions += solver_actions
        

        print(f"🛠️ SolverBot took {solver_actions} actions. Total cumulative: {total_actions}/{max_actions}")
        if total_actions >= max_actions:
            print(f"🛑 Cumulative action count {total_actions} ≥ {max_actions} → Exiting.")
            break

    return solver_total


def main(config_path="config.yaml", games_path="./json/game_prompt.json", game_name_arg=None):
    config = load_config(config_path)
    max_actions = config.get("max_action_count", 50)

    game_dict = load_game_metadata(games_path)
    if game_name_arg:
        game_name = game_name_arg
    else:
        game_name = choose_game(game_dict)
    print(f"\n🎯 Selected Game: {game_name}")

    MAX_ITER = 10
    total_actions = 0
    total_seeker = 0
    total_solver = 0
    iteration = 0

    while iteration < MAX_ITER:
        print(f"\n🔁 [Iteration {iteration + 1}] Starting")
        print(f"🔢 Current cumulative action count: {total_actions}/{max_actions}")
        iteration += 1

        # 1. Clue Seeking
        seeker_actions = run_clue_seeker(config_path, game_name)
        total_seeker += seeker_actions
        total_actions += seeker_actions
        print(f"🔍 ClueSeeker took {seeker_actions} actions. Total cumulative: {total_actions}/{max_actions}")

        if total_actions >= max_actions:
            print(f"🛑 Cumulative action count {total_actions} ≥ {max_actions} → Exiting.")
            break

        # 2. Mapping
        memory_path = run_mapper(config_path, game_name)

        # 3. Load Mapping Results
        mapping_file = os.path.join(memory_path, "mapping_memory.json")
        mappings = load_mapping_data(mapping_file)

        if not mappings:
            print("📭 No mapping results → Assuming insufficient clues and retrying seeker")
            continue

        failed = [m for m in mappings if isinstance(m, dict) and not m.get("success", False)]
        if not failed:
            print("🎉 All mappings successful! Exiting.")
            break

        print(f"⚠️ Failed mappings: {len(failed)}")

        # 4. Run Solver
        solver_actions = run_solver(config_path, game_name, failed, total_actions, max_actions)
        total_solver += solver_actions
        total_actions += solver_actions

        print(f"🧮 Cumulative action count after Solver: {total_actions}/{max_actions}")

        if total_actions >= max_actions:
            break

        remaining_failed = [m for m in load_mapping_data(mapping_file) if isinstance(m, dict) and not m.get("success", False)]
        if not remaining_failed:
            print("✅ All mappings resolved successfully. Exiting.")
            break
        else:
            print(f"⚠️ Still have failed mappings: {len(remaining_failed)} → Proceeding to next loop")

    else:
        print("🛑 Reached max iterations. Exiting with some mappings failed.")

    # Final Report
    print("\n📊 Final Action Summary")
    print(f"🔍 ClueSeeker total actions: {total_seeker}")
    print(f"🛠️ SolverBot total actions: {total_solver}")
    print(f"📦 Total cumulative actions: {total_actions}/{max_actions}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Clue→Map→Solve pipeline for selected game")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--games", type=str, default="games.json", help="Path to games.json")
    parser.add_argument("--game", type=str, default=None, help="Game name (skips interactive selection)")
    args = parser.parse_args()

    main(config_path=args.config, games_path="./json/game_prompt.json", game_name_arg=args.game)