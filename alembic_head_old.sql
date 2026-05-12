BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> a4e74831560c

CREATE TABLE experiences (
    name VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    status VARCHAR NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_experiences_name_org_app UNIQUE (name, organisation_id, app_id)
);

CREATE INDEX idx_experiences_name_org_app ON experiences (name, organisation_id, app_id);

CREATE INDEX idx_experiences_org_app ON experiences (organisation_id, app_id);

CREATE INDEX idx_experiences_status_org_app ON experiences (status, organisation_id, app_id);

CREATE UNIQUE INDEX ix_experiences_id ON experiences (id);

CREATE UNIQUE INDEX ix_experiences_pid ON experiences (pid);

CREATE TABLE feature_flags (
    name VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    keys_config JSON DEFAULT json('{}') NOT NULL, 
    type VARCHAR NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_feature_flags_name_org_app UNIQUE (name, organisation_id, app_id)
);

CREATE INDEX idx_feature_flags_active_org_app ON feature_flags (is_active, organisation_id, app_id);

CREATE INDEX idx_feature_flags_org_app ON feature_flags (organisation_id, app_id);

CREATE UNIQUE INDEX ix_feature_flags_id ON feature_flags (id);

CREATE UNIQUE INDEX ix_feature_flags_pid ON feature_flags (pid);

CREATE TABLE metrics (
    name VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    type VARCHAR NOT NULL, 
    config JSON DEFAULT json('{}') NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX idx_metrics_name_org_app ON metrics (name, organisation_id, app_id);

CREATE INDEX idx_metrics_org_app ON metrics (organisation_id, app_id);

CREATE UNIQUE INDEX ix_metrics_id ON metrics (id);

CREATE UNIQUE INDEX ix_metrics_pid ON metrics (pid);

CREATE TABLE segments (
    name VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    rule_config JSON DEFAULT json('{}') NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_segments_name_org_app UNIQUE (name, organisation_id, app_id)
);

CREATE INDEX idx_segments_org_app ON segments (organisation_id, app_id);

CREATE UNIQUE INDEX ix_segments_id ON segments (id);

CREATE UNIQUE INDEX ix_segments_pid ON segments (pid);

CREATE TABLE users (
    user_id VARCHAR NOT NULL, 
    user_profile JSON DEFAULT json('{}') NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_users_user_id_org_app UNIQUE (user_id, organisation_id, app_id)
);

CREATE INDEX idx_users_org_app ON users (organisation_id, app_id);

CREATE INDEX idx_users_user_id_org_app ON users (user_id, organisation_id, app_id);

CREATE UNIQUE INDEX ix_users_id ON users (id);

CREATE UNIQUE INDEX ix_users_pid ON users (pid);

CREATE TABLE experience_features (
    experience_id UUID NOT NULL, 
    feature_id UUID NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid), 
    FOREIGN KEY(feature_id) REFERENCES feature_flags (pid), 
    CONSTRAINT uq_experience_features_exp_feat UNIQUE (experience_id, feature_id)
);

CREATE INDEX idx_experience_features_experience_id ON experience_features (experience_id);

CREATE INDEX idx_experience_features_feature_flag_id ON experience_features (feature_id);

CREATE UNIQUE INDEX ix_experience_features_id ON experience_features (id);

CREATE UNIQUE INDEX ix_experience_features_pid ON experience_features (pid);

CREATE TABLE experience_metrics (
    experience_id UUID NOT NULL, 
    metric_id UUID NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid), 
    FOREIGN KEY(metric_id) REFERENCES metrics (pid), 
    CONSTRAINT uq_experience_metrics_exp_metric UNIQUE (experience_id, metric_id)
);

CREATE INDEX ix_experience_metrics_experience_id ON experience_metrics (experience_id);

CREATE UNIQUE INDEX ix_experience_metrics_id ON experience_metrics (id);

CREATE INDEX ix_experience_metrics_metric_id ON experience_metrics (metric_id);

CREATE UNIQUE INDEX ix_experience_metrics_pid ON experience_metrics (pid);

CREATE TABLE experience_variants (
    name VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    experience_id UUID NOT NULL, 
    is_default BOOLEAN NOT NULL, 
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid), 
    CONSTRAINT uq_experience_variants_name_exp UNIQUE (name, experience_id)
);

CREATE INDEX idx_experience_variants_experience_id ON experience_variants (experience_id);

CREATE UNIQUE INDEX ix_experience_variants_id ON experience_variants (id);

CREATE UNIQUE INDEX ix_experience_variants_pid ON experience_variants (pid);

CREATE TABLE personalisations (
    name VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    experience_id UUID NOT NULL, 
    priority INTEGER NOT NULL, 
    rule_config JSON DEFAULT json('{}') NOT NULL, 
    rollout_percentage INTEGER NOT NULL, 
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid), 
    CONSTRAINT uq_personalisations_exp_prio UNIQUE (experience_id, priority), 
    CONSTRAINT uq_personalisations_name_exp UNIQUE (name, experience_id)
);

CREATE INDEX idx_personalisations_experience_id ON personalisations (experience_id);

CREATE INDEX idx_personalisations_priority ON personalisations (priority);

CREATE UNIQUE INDEX ix_personalisations_id ON personalisations (id);

CREATE UNIQUE INDEX ix_personalisations_pid ON personalisations (pid);

CREATE TABLE experience_feature_variants (
    experience_variant_id UUID NOT NULL, 
    experience_feature_id UUID NOT NULL, 
    name VARCHAR NOT NULL, 
    config JSON DEFAULT json('{}') NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_feature_id) REFERENCES experience_features (pid), 
    FOREIGN KEY(experience_variant_id) REFERENCES experience_variants (pid)
);

CREATE INDEX idx_experience_feature_variants_experience_feature_id ON experience_feature_variants (experience_feature_id);

CREATE UNIQUE INDEX ix_experience_feature_variants_id ON experience_feature_variants (id);

CREATE UNIQUE INDEX ix_experience_feature_variants_pid ON experience_feature_variants (pid);

CREATE TABLE personalisation_experience_variants (
    personalisation_id UUID NOT NULL, 
    experience_variant_id UUID NOT NULL, 
    target_percentage INTEGER NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_variant_id) REFERENCES experience_variants (pid), 
    FOREIGN KEY(personalisation_id) REFERENCES personalisations (pid), 
    CONSTRAINT uq_personalisation_experience_variants_per_exp_var UNIQUE (personalisation_id, experience_variant_id)
);

CREATE INDEX ix_personalisation_experience_variants_experience_variant_id ON personalisation_experience_variants (experience_variant_id);

CREATE UNIQUE INDEX ix_personalisation_experience_variants_id ON personalisation_experience_variants (id);

CREATE INDEX ix_personalisation_experience_variants_personalisation_id ON personalisation_experience_variants (personalisation_id);

CREATE UNIQUE INDEX ix_personalisation_experience_variants_pid ON personalisation_experience_variants (pid);

CREATE TABLE personalisation_metrics (
    personalisation_id UUID NOT NULL, 
    metric_id UUID NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(metric_id) REFERENCES metrics (pid), 
    FOREIGN KEY(personalisation_id) REFERENCES personalisations (pid), 
    CONSTRAINT uq_personalisation_metrics_pers_metric UNIQUE (personalisation_id, metric_id)
);

CREATE UNIQUE INDEX ix_personalisation_metrics_id ON personalisation_metrics (id);

CREATE INDEX ix_personalisation_metrics_metric_id ON personalisation_metrics (metric_id);

CREATE INDEX ix_personalisation_metrics_personalisation_id ON personalisation_metrics (personalisation_id);

CREATE UNIQUE INDEX ix_personalisation_metrics_pid ON personalisation_metrics (pid);

CREATE TABLE personalisation_segment_rules (
    personalisation_id UUID NOT NULL, 
    segment_id UUID NOT NULL, 
    rule_config JSON DEFAULT json('{}') NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(personalisation_id) REFERENCES personalisations (pid), 
    FOREIGN KEY(segment_id) REFERENCES segments (pid), 
    CONSTRAINT uq_personalisation_segment_rules_tr_seg UNIQUE (personalisation_id, segment_id)
);

CREATE UNIQUE INDEX ix_personalisation_segment_rules_id ON personalisation_segment_rules (id);

CREATE INDEX ix_personalisation_segment_rules_personalisation_id ON personalisation_segment_rules (personalisation_id);

CREATE UNIQUE INDEX ix_personalisation_segment_rules_pid ON personalisation_segment_rules (pid);

CREATE INDEX ix_personalisation_segment_rules_segment_id ON personalisation_segment_rules (segment_id);

CREATE TABLE user_experience_personalisation (
    user_id UUID NOT NULL, 
    experience_id UUID NOT NULL, 
    personalisation_id UUID, 
    segment_name VARCHAR, 
    segment_id UUID, 
    experience_segment_id UUID, 
    experience_segment_personalisation_id UUID, 
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    evaluation_reason VARCHAR NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid), 
    FOREIGN KEY(personalisation_id) REFERENCES personalisations (pid), 
    FOREIGN KEY(user_id) REFERENCES users (pid), 
    CONSTRAINT uq_user_experience_user_exp_org_app UNIQUE (user_id, experience_id, organisation_id, app_id)
);

CREATE INDEX idx_user_experience_assigned_org_app ON user_experience_personalisation (assigned_at, organisation_id, app_id);

CREATE INDEX idx_user_experience_experience_org_app ON user_experience_personalisation (experience_id, organisation_id, app_id);

CREATE INDEX idx_user_experience_main_query ON user_experience_personalisation (user_id, organisation_id, app_id, experience_id);

CREATE INDEX idx_user_experience_user_assigned ON user_experience_personalisation (user_id, assigned_at);

CREATE UNIQUE INDEX ix_user_experience_personalisation_id ON user_experience_personalisation (id);

CREATE UNIQUE INDEX ix_user_experience_personalisation_pid ON user_experience_personalisation (pid);

INSERT INTO alembic_version (version_num) VALUES ('a4e74831560c') RETURNING alembic_version.version_num;

-- Running upgrade a4e74831560c -> ba3f9b96fb79

ALTER TABLE user_experience_personalisation DROP CONSTRAINT uq_user_experience_user_exp_org_app;

DROP INDEX idx_user_experience_assigned_org_app;

DROP INDEX idx_user_experience_experience_org_app;

DROP INDEX idx_user_experience_main_query;

DROP INDEX idx_user_experience_user_assigned;

DROP INDEX ix_user_experience_personalisation_id;

DROP INDEX ix_user_experience_personalisation_pid;

DROP TABLE user_experience_personalisation;

CREATE TABLE user_experience (
    user_id UUID NOT NULL, 
    experience_id UUID NOT NULL, 
    personalisation_id UUID, 
    personalisation_name VARCHAR, 
    features JSON DEFAULT json('{}') NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    evaluation_reason VARCHAR NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid), 
    FOREIGN KEY(personalisation_id) REFERENCES personalisations (pid), 
    FOREIGN KEY(user_id) REFERENCES users (pid), 
    CONSTRAINT uq_user_experience_user_exp_org_app UNIQUE (user_id, experience_id, organisation_id, app_id)
);

CREATE INDEX idx_user_experience_assigned_org_app ON user_experience (assigned_at, organisation_id, app_id);

CREATE INDEX idx_user_experience_experience_org_app ON user_experience (experience_id, organisation_id, app_id);

CREATE INDEX idx_user_experience_main_query ON user_experience (user_id, organisation_id, app_id, experience_id);

CREATE INDEX idx_user_experience_user_assigned ON user_experience (user_id, assigned_at);

CREATE UNIQUE INDEX ix_user_experience_id ON user_experience (id);

CREATE UNIQUE INDEX ix_user_experience_pid ON user_experience (pid);

UPDATE alembic_version SET version_num='ba3f9b96fb79' WHERE alembic_version.version_num = 'a4e74831560c';

-- Running upgrade ba3f9b96fb79 -> ad43f07058e3

CREATE TABLE recommendations (
    experience_id UUID NOT NULL, 
    personalisation_data JSON NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (pid)
);

CREATE UNIQUE INDEX ix_recommendations_id ON recommendations (id);

CREATE UNIQUE INDEX ix_recommendations_pid ON recommendations (pid);

UPDATE alembic_version SET version_num='ad43f07058e3' WHERE alembic_version.version_num = 'ba3f9b96fb79';

-- Running upgrade ad43f07058e3 -> cc00f8f5f444

CREATE TABLE events_schema (
    event_name VARCHAR NOT NULL, 
    event_schema JSON DEFAULT json('{}') NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_events_schema_event_name_org_app UNIQUE (event_name, organisation_id, app_id)
);

CREATE INDEX idx_events_schema_event_name_org_app ON events_schema (event_name, organisation_id, app_id);

CREATE UNIQUE INDEX ix_events_schema_id ON events_schema (id);

CREATE UNIQUE INDEX ix_events_schema_pid ON events_schema (pid);

ALTER TABLE user_experience ADD COLUMN experience_variant_id UUID;

UPDATE alembic_version SET version_num='cc00f8f5f444' WHERE alembic_version.version_num = 'ad43f07058e3';

-- Running upgrade cc00f8f5f444 -> 3895c4350d44

CREATE TABLE user_profile_keys (
    key VARCHAR NOT NULL, 
    type VARCHAR NOT NULL, 
    description VARCHAR NOT NULL, 
    organisation_id VARCHAR NOT NULL, 
    app_id VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_user_profile_keys_key_org_app UNIQUE (key, organisation_id, app_id)
);

CREATE INDEX idx_user_profile_keys_org_app ON user_profile_keys (organisation_id, app_id);

CREATE UNIQUE INDEX ix_user_profile_keys_id ON user_profile_keys (id);

CREATE UNIQUE INDEX ix_user_profile_keys_pid ON user_profile_keys (pid);

CREATE INDEX idx_events_schema_org_app ON events_schema (organisation_id, app_id);

UPDATE alembic_version SET version_num='3895c4350d44' WHERE alembic_version.version_num = 'cc00f8f5f444';

-- Running upgrade 3895c4350d44 -> 0a99ede8830e

CREATE TABLE organisations (
    name VARCHAR NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_organisations_id ON organisations (id);

CREATE UNIQUE INDEX ix_organisations_pid ON organisations (pid);

CREATE TABLE apps (
    name VARCHAR NOT NULL, 
    organisation_id UUID NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organisation_id) REFERENCES organisations (pid)
);

CREATE UNIQUE INDEX ix_apps_id ON apps (id);

CREATE UNIQUE INDEX ix_apps_pid ON apps (pid);

CREATE TABLE auth_users (
    name VARCHAR NOT NULL, 
    email VARCHAR NOT NULL, 
    password VARCHAR NOT NULL, 
    organisation_id UUID NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organisation_id) REFERENCES organisations (pid)
);

CREATE UNIQUE INDEX ix_auth_users_id ON auth_users (id);

CREATE UNIQUE INDEX ix_auth_users_pid ON auth_users (pid);

UPDATE alembic_version SET version_num='0a99ede8830e' WHERE alembic_version.version_num = '3895c4350d44';

-- Running upgrade 0a99ede8830e -> e43cccdcac6e

CREATE TYPE userrole AS ENUM ('OWNER', 'ADMIN', 'MEMBER');

CREATE TYPE invitationstatus AS ENUM ('PENDING', 'ACCEPTED', 'EXPIRED', 'CANCELLED');

CREATE TABLE invitations (
    email VARCHAR(255) NOT NULL, 
    organisation_id UUID NOT NULL, 
    role userrole NOT NULL, 
    token VARCHAR(255) NOT NULL, 
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    invited_by UUID NOT NULL, 
    status invitationstatus NOT NULL, 
    id SERIAL NOT NULL, 
    pid UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(invited_by) REFERENCES auth_users (pid), 
    FOREIGN KEY(organisation_id) REFERENCES organisations (pid), 
    UNIQUE (token)
);

CREATE UNIQUE INDEX ix_invitations_id ON invitations (id);

CREATE UNIQUE INDEX ix_invitations_pid ON invitations (pid);

ALTER TABLE auth_users ADD COLUMN role userrole NOT NULL;

UPDATE alembic_version SET version_num='e43cccdcac6e' WHERE alembic_version.version_num = '0a99ede8830e';

-- Running upgrade e43cccdcac6e -> 2b489cdf6ff0

CREATE INDEX ix_apps_org_name ON apps (organisation_id, name);

CREATE INDEX ix_apps_organisation_id ON apps (organisation_id);

ALTER TABLE apps ADD CONSTRAINT uq_org_app_name UNIQUE (organisation_id, name);

CREATE UNIQUE INDEX ix_auth_users_email ON auth_users (email);

CREATE INDEX ix_auth_users_organisation_id ON auth_users (organisation_id);

CREATE INDEX ix_invitations_email_org_status ON invitations (email, organisation_id, status);

CREATE INDEX ix_invitations_expires_status ON invitations (expires_at, status);

CREATE INDEX ix_invitations_org_status_created ON invitations (organisation_id, status, created_at);

UPDATE alembic_version SET version_num='2b489cdf6ff0' WHERE alembic_version.version_num = 'e43cccdcac6e';

-- Running upgrade 2b489cdf6ff0 -> 1829a24adbfb

ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'DEVELOPER';

ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'ANALYST';

UPDATE alembic_version SET version_num='1829a24adbfb' WHERE alembic_version.version_num = '2b489cdf6ff0';

-- Running upgrade 1829a24adbfb -> 929afc1b3223

ALTER TABLE personalisations ADD COLUMN is_active BOOLEAN DEFAULT 'true' NOT NULL;

UPDATE alembic_version SET version_num='929afc1b3223' WHERE alembic_version.version_num = '1829a24adbfb';

-- Running upgrade 929afc1b3223 -> 370cd2a18b69

ALTER TABLE personalisations ADD COLUMN reassign BOOLEAN DEFAULT 'false' NOT NULL;

DROP INDEX idx_user_experience_main_query;

ALTER TABLE user_experience DROP CONSTRAINT uq_user_experience_user_exp_org_app;

CREATE INDEX idx_user_experience_user_org_app_exp_id ON user_experience (user_id, organisation_id, app_id, experience_id, id);

UPDATE alembic_version SET version_num='370cd2a18b69' WHERE alembic_version.version_num = '929afc1b3223';

-- Running upgrade 370cd2a18b69 -> 20d7fa647c5e

DROP INDEX idx_personalisations_experience_id;

DROP INDEX idx_personalisations_priority;

CREATE INDEX idx_personalisations_exp_active_priority ON personalisations (experience_id, is_active, priority);

CREATE INDEX idx_personalisations_org_app_search ON personalisations (organisation_id, app_id, name, created_at);

UPDATE alembic_version SET version_num='20d7fa647c5e' WHERE alembic_version.version_num = '370cd2a18b69';

COMMIT;

