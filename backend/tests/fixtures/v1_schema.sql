-- v1 schema: what v1's Base.metadata.create_all() created (backend/app/models.py at
-- commit 402f117, the last release before Alembic). Used by test_migrations.py to
-- prove a pre-migration database upgrades in place. Do not edit.

CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	google_id VARCHAR(255) NOT NULL, 
	telegram_chat_id BIGINT, 
	interest_profile_text TEXT, 
	interest_vector FLOAT[], 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (telegram_chat_id)
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE UNIQUE INDEX ix_users_google_id ON users (google_id);

CREATE TABLE connection_codes (
	id SERIAL NOT NULL, 
	code VARCHAR(16) NOT NULL, 
	user_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE UNIQUE INDEX ix_connection_codes_code ON connection_codes (code);

CREATE TABLE loopwire_sends (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	period VARCHAR(20) NOT NULL, 
	sent_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	item_count INTEGER NOT NULL, 
	email_sent BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_loopwire_sends_user_id ON loopwire_sends (user_id);

CREATE TABLE saved_items (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	url TEXT NOT NULL, 
	type VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	raw_message_text TEXT, 
	telegram_user_id BIGINT, 
	telegram_chat_id BIGINT, 
	added_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	title TEXT, 
	author TEXT, 
	published_date VARCHAR(50), 
	clean_text TEXT, 
	extraction_success BOOLEAN, 
	extraction_error TEXT, 
	extracted_at TIMESTAMP WITH TIME ZONE, 
	summary TEXT, 
	key_takeaway TEXT, 
	relevance_note TEXT, 
	estimated_read_time_minutes INTEGER, 
	summarized_at TIMESTAMP WITH TIME ZONE, 
	embedding FLOAT[], 
	loopwire_send_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(loopwire_send_id) REFERENCES loopwire_sends (id)
);
CREATE INDEX ix_saved_items_user_id ON saved_items (user_id);

CREATE TABLE engagement_events (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	item_id INTEGER NOT NULL, 
	event_type VARCHAR(20) NOT NULL, 
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(item_id) REFERENCES saved_items (id)
);
CREATE INDEX ix_engagement_events_user_id ON engagement_events (user_id);
