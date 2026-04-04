-- depends: 0013_add_steam_tag_id

ALTER TABLE tags ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'Other';

UPDATE tags SET category = 'Genre' WHERE name IN (
    'Action', 'Adventure', 'RPG', 'Strategy', 'Simulation', 'Puzzle', 'Platformer',
    'Racing', 'Sports', 'Shooter', 'Fighting', 'Card Game', 'Board Game', 'Rhythm',
    'Trivia', 'Pinball', 'Word Game'
);

UPDATE tags SET category = 'Sub-Genre' WHERE name IN (
    'Action-Adventure', 'Action Roguelike', 'Action RPG', 'Action RTS', 'Arcade',
    'Arena Shooter', 'Auto Battler', 'Battle Royale', 'Beat ''em up', 'Boomer Shooter',
    'Boss Rush', 'Bullet Hell', 'Card Battler', 'Character Action Game', 'City Builder',
    'Clicker', 'Colony Sim', 'CRPG', 'Dating Sim', 'Deckbuilding', 'Dungeon Crawler',
    'Escape Room', 'Extraction Shooter', 'FPS', 'God Game', 'Grand Strategy',
    'Hack and Slash', 'Hero Shooter', 'Hidden Object', 'Idler', 'Immersive Sim',
    'Interactive Fiction', 'JRPG', 'Life Sim', 'Looter Shooter', 'Match 3',
    'Metroidvania', 'MMORPG', 'MOBA', 'Musou', 'Mystery Dungeon', 'On-Rails Shooter',
    'Open World Survival Craft', 'Otome', 'Party-Based RPG', 'Point & Click',
    'Precision Platformer', 'Puzzle Platformer', 'Real Time Tactics', 'Roguelike',
    'Roguelike Deckbuilder', 'Roguelite', 'Roguevania', 'RPGMaker', 'RTS', 'Runner',
    'Shoot ''Em Up', 'Side Scroller', 'Sokoban', 'Solitaire', 'Souls-like', 'Space Sim',
    'Spectacle fighter', 'Strategy RPG', 'Survival Horror', 'Tabletop', 'Tactical RPG',
    'Third-Person Shooter', 'Top-Down Shooter', 'Tower Defense', 'Trading Card Game',
    'Traditional Roguelike', 'Turn-Based Combat', 'Turn-Based Strategy',
    'Turn-Based Tactics', 'Twin Stick Shooter', 'Visual Novel', 'Walking Simulator',
    'Wargame', '2D Fighter', '2D Platformer', '3D Fighter', '3D Platformer', '4X',
    'Automobile Sim', 'Farming Sim', 'Hobby Sim', 'Job Simulator', 'Medical Sim',
    'Outbreak Sim', 'Political Sim', 'Shop Keeper'
);

UPDATE tags SET category = 'Theme & Setting' WHERE name IN (
    'Aliens', 'Alternate History', 'America', 'Anime', 'Assassination', 'Capitalism',
    'Cats', 'Cold War', 'Comic Book', 'Conspiracy', 'Crime', 'Cyberpunk', 'Dark Fantasy',
    'Demons', 'Dinosaurs', 'Dog', 'Dragons', 'Dungeons & Dragons', 'Dwarf', 'Dystopian',
    'Elf', 'Faith', 'Fantasy', 'Foreign', 'Fox', 'Futuristic', 'Games Workshop', 'Gothic',
    'Hacking', 'Heist', 'Historical', 'Horses', 'Illuminati', 'LEGO', 'Lovecraftian',
    'Magic', 'Mars', 'Martial Arts', 'Mechs', 'Medieval', 'Military', 'Modern',
    'Mythology', 'Nature', 'Naval', 'Ninja', 'Noir', 'Nostalgia', 'Parkour', 'Pirates',
    'Post-apocalyptic', 'Psychedelic', 'Robots', 'Rome', 'Romance', 'Sailing', 'Sci-fi',
    'Science', 'Snow', 'Space', 'Spaceships', 'Steampunk', 'Submarine', 'Superhero',
    'Supernatural', 'Surreal', 'Swordplay', 'Tanks', 'Time Travel', 'Trains',
    'Transhumanism', 'Underground', 'Underwater', 'Vampire', 'Vikings', 'Warhammer 40K',
    'War', 'Werewolves', 'Western', 'World War I', 'World War II', 'Zombies', 'Birds',
    'Lemmings'
);

UPDATE tags SET category = 'Gameplay' WHERE name IN (
    'Base Building', 'Building', 'Choices Matter', 'Choose Your Own Adventure', 'Co-op',
    'Co-op Campaign', 'Combat', 'Combat Racing', 'Competitive', 'Controller', 'Cooking',
    'Crafting', 'Creature Collector', 'Destruction', 'Dice', 'Diplomacy', 'Driving',
    'Dynamic Narration', 'Economy', 'Exploration', 'Farming', 'Fishing', 'Flight',
    'Gambling', 'Grid-Based Movement', 'Gun Customization', 'Hex Grid', 'Hunting',
    'Inventory Management', 'Investigation', 'Level Editor', 'Loot', 'Management',
    'Mining', 'Mod', 'Moddable', 'Multiple Endings', 'Narration', 'Narrative',
    'Naval Combat', 'Nonlinear', 'Open World', 'Perma Death', 'Physics',
    'Procedural Generation', 'Programming', 'PvE', 'PvP', 'Quick-Time Events',
    'Real-Time', 'Real-Time with Pause', 'Resource Management', 'Sandbox', 'Score Attack',
    'Social Deduction', 'Stealth', 'Survival', 'Team-Based', 'Time Attack',
    'Time Management', 'Time Manipulation', 'Touch-Friendly', 'Trading', 'Turn-Based',
    'Typing', 'Vehicular Combat', 'Voice Control', 'Character Customization',
    'Class-Based', 'Collectathon', 'Archery', 'Bowling', 'Boxing', 'Cricket', 'Cycling',
    'Golf', 'Hockey', 'Mini Golf', 'Pool', 'Skateboarding', 'Skating', 'Skiing',
    'Snooker', 'Snowboarding', 'Tennis', 'Volleyball', 'Wrestling', 'Baseball',
    'Basketball', 'Football (American)', 'Football (Soccer)', 'Rugby', 'Offroad',
    'Motocross', 'Motorbike', 'BMX', 'ATV', 'Bikes', 'Jet', 'Sniper', 'Bullet Time'
);

UPDATE tags SET category = 'Player Mode' WHERE name IN (
    'Singleplayer', 'Multiplayer', 'Local Co-Op', 'Local Multiplayer', 'Online Co-Op',
    'Massively Multiplayer', 'Split Screen', 'Asynchronous Multiplayer', '4 Player Local',
    'Party Game', 'Party', 'eSports'
);

UPDATE tags SET category = 'Visuals & Viewpoint' WHERE name IN (
    '2D', '2.5D', '3D', 'First-Person', 'Third Person', 'Top-Down', 'Isometric',
    'Pixel Graphics', 'Voxel', 'Hand-drawn', 'Cartoon', 'Cartoony', 'Colorful',
    'Minimalist', 'Realistic', 'Stylized', 'Cinematic', 'Beautiful', 'Abstract', 'VR',
    'Asymmetric VR', '360 Video', '3D Vision', '6DOF', 'FMV', 'TrackIR', 'Mouse only',
    'Text-Based'
);

UPDATE tags SET category = 'Mood & Tone' WHERE name IN (
    'Atmospheric', 'Casual', 'Cozy', 'Cute', 'Dark', 'Dark Comedy', 'Dark Humor',
    'Difficult', 'Drama', 'Emotional', 'Epic', 'Experimental', 'Family Friendly',
    'Fast-Paced', 'Funny', 'Comedy', 'Gore', 'Blood', 'Great Soundtrack', 'Horror',
    'Immersive', 'Jump Scare', 'Linear', 'Lore-Rich', 'Mature', 'Memes', 'NSFW',
    'Nudity', 'Sexual Content', 'Hentai', 'Parody', 'Philosophical', 'Political',
    'Politics', 'Psychological', 'Psychological Horror', 'Relaxing', 'Replay Value',
    'Retro', 'Satire', 'Short', 'Silent Protagonist', 'Story Rich', 'Thriller',
    'Unforgiving', 'Villain Protagonist', 'Violent', 'Well-Written', 'Wholesome',
    'Addictive', 'Classic', 'Cult Classic', 'Intentionally Awkward Controls', 'Old School',
    'LGBTQ+', 'Female Protagonist', 'Sequel', 'Remake', 'Reboot'
);

-- 'Other' is the column default — no UPDATE needed for that category.

CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category);
