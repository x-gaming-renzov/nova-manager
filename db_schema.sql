
-- TABLE: public.alembic_version
version_num character varying nullable=NO default=None

-- TABLE: public.apps
name character varying nullable=NO default=None
organisation_id uuid nullable=NO default=None
id integer nullable=NO default=nextval('apps_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.auth_users
name character varying nullable=NO default=None
email character varying nullable=NO default=None
password character varying nullable=NO default=None
organisation_id uuid nullable=NO default=None
id integer nullable=NO default=nextval('auth_users_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()
role USER-DEFINED nullable=NO default=None

-- TABLE: public.events_schema
event_name character varying nullable=NO default=None
event_schema json nullable=NO default=JSON('{}'::text)
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('events_schema_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.experience_feature_variants
experience_variant_id uuid nullable=NO default=None
experience_feature_id uuid nullable=NO default=None
name character varying nullable=NO default=None
config json nullable=NO default=JSON('{}'::text)
id integer nullable=NO default=nextval('experience_feature_variants_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.experience_features
experience_id uuid nullable=NO default=None
feature_id uuid nullable=NO default=None
id integer nullable=NO default=nextval('experience_features_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.experience_metrics
experience_id uuid nullable=NO default=None
metric_id uuid nullable=NO default=None
id integer nullable=NO default=nextval('experience_metrics_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.experience_variants
name character varying nullable=NO default=None
description character varying nullable=NO default=None
experience_id uuid nullable=NO default=None
is_default boolean nullable=NO default=None
last_updated_at timestamp with time zone nullable=NO default=now()
id integer nullable=NO default=nextval('experience_variants_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.experiences
name character varying nullable=NO default=None
description character varying nullable=NO default=None
status character varying nullable=NO default=None
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('experiences_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.feature_flags
name character varying nullable=NO default=None
description character varying nullable=NO default=None
keys_config json nullable=NO default=JSON('{}'::text)
type character varying nullable=NO default=None
is_active boolean nullable=NO default=None
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('feature_flags_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.invitations
email character varying nullable=NO default=None
organisation_id uuid nullable=NO default=None
role USER-DEFINED nullable=NO default=None
token character varying nullable=NO default=None
expires_at timestamp without time zone nullable=NO default=None
invited_by uuid nullable=NO default=None
status USER-DEFINED nullable=NO default=None
id integer nullable=NO default=nextval('invitations_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.metrics
name character varying nullable=NO default=None
description character varying nullable=NO default=None
type character varying nullable=NO default=None
config json nullable=NO default=JSON('{}'::text)
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('metrics_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.organisations
name character varying nullable=NO default=None
id integer nullable=NO default=nextval('organisations_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.personalisation_experience_variants
personalisation_id uuid nullable=NO default=None
experience_variant_id uuid nullable=NO default=None
target_percentage integer nullable=NO default=None
id integer nullable=NO default=nextval('personalisation_experience_variants_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.personalisation_metrics
personalisation_id uuid nullable=NO default=None
metric_id uuid nullable=NO default=None
id integer nullable=NO default=nextval('personalisation_metrics_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.personalisation_segment_rules
personalisation_id uuid nullable=NO default=None
segment_id uuid nullable=NO default=None
rule_config json nullable=NO default=JSON('{}'::text)
id integer nullable=NO default=nextval('personalisation_segment_rules_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.personalisations
name character varying nullable=NO default=None
description character varying nullable=NO default=None
experience_id uuid nullable=NO default=None
priority integer nullable=NO default=None
rule_config json nullable=NO default=JSON('{}'::text)
rollout_percentage integer nullable=NO default=None
last_updated_at timestamp with time zone nullable=NO default=now()
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('personalisations_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()
is_active boolean nullable=NO default=true
reassign boolean nullable=NO default=false

-- TABLE: public.recommendations
experience_id uuid nullable=NO default=None
personalisation_data json nullable=NO default=None
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('recommendations_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.segments
name character varying nullable=NO default=None
description character varying nullable=NO default=None
rule_config json nullable=NO default=JSON('{}'::text)
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('segments_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.user_experience
user_id uuid nullable=NO default=None
experience_id uuid nullable=NO default=None
personalisation_id uuid nullable=YES default=None
personalisation_name character varying nullable=YES default=None
features json nullable=NO default=JSON('{}'::text)
assigned_at timestamp with time zone nullable=NO default=now()
evaluation_reason character varying nullable=NO default=None
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('user_experience_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()
experience_variant_id uuid nullable=YES default=None

-- TABLE: public.user_profile_keys
key character varying nullable=NO default=None
type character varying nullable=NO default=None
description character varying nullable=NO default=None
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('user_profile_keys_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- TABLE: public.users
user_id character varying nullable=NO default=None
user_profile json nullable=NO default=JSON('{}'::text)
organisation_id character varying nullable=NO default=None
app_id character varying nullable=NO default=None
id integer nullable=NO default=nextval('users_id_seq'::regclass)
pid uuid nullable=NO default=None
created_at timestamp with time zone nullable=NO default=now()
modified_at timestamp with time zone nullable=NO default=now()

-- INDEXES
public.alembic_version alembic_version_pkc CREATE UNIQUE INDEX alembic_version_pkc ON public.alembic_version USING btree (version_num)
public.apps apps_pkey CREATE UNIQUE INDEX apps_pkey ON public.apps USING btree (id)
public.apps ix_apps_id CREATE UNIQUE INDEX ix_apps_id ON public.apps USING btree (id)
public.apps ix_apps_org_name CREATE INDEX ix_apps_org_name ON public.apps USING btree (organisation_id, name)
public.apps ix_apps_organisation_id CREATE INDEX ix_apps_organisation_id ON public.apps USING btree (organisation_id)
public.apps ix_apps_pid CREATE UNIQUE INDEX ix_apps_pid ON public.apps USING btree (pid)
public.apps uq_org_app_name CREATE UNIQUE INDEX uq_org_app_name ON public.apps USING btree (organisation_id, name)
public.auth_users auth_users_pkey CREATE UNIQUE INDEX auth_users_pkey ON public.auth_users USING btree (id)
public.auth_users ix_auth_users_email CREATE UNIQUE INDEX ix_auth_users_email ON public.auth_users USING btree (email)
public.auth_users ix_auth_users_id CREATE UNIQUE INDEX ix_auth_users_id ON public.auth_users USING btree (id)
public.auth_users ix_auth_users_organisation_id CREATE INDEX ix_auth_users_organisation_id ON public.auth_users USING btree (organisation_id)
public.auth_users ix_auth_users_pid CREATE UNIQUE INDEX ix_auth_users_pid ON public.auth_users USING btree (pid)
public.events_schema events_schema_pkey CREATE UNIQUE INDEX events_schema_pkey ON public.events_schema USING btree (id)
public.events_schema idx_events_schema_event_name_org_app CREATE INDEX idx_events_schema_event_name_org_app ON public.events_schema USING btree (event_name, organisation_id, app_id)
public.events_schema idx_events_schema_org_app CREATE INDEX idx_events_schema_org_app ON public.events_schema USING btree (organisation_id, app_id)
public.events_schema ix_events_schema_id CREATE UNIQUE INDEX ix_events_schema_id ON public.events_schema USING btree (id)
public.events_schema ix_events_schema_pid CREATE UNIQUE INDEX ix_events_schema_pid ON public.events_schema USING btree (pid)
public.events_schema uq_events_schema_event_name_org_app CREATE UNIQUE INDEX uq_events_schema_event_name_org_app ON public.events_schema USING btree (event_name, organisation_id, app_id)
public.experience_feature_variants experience_feature_variants_pkey CREATE UNIQUE INDEX experience_feature_variants_pkey ON public.experience_feature_variants USING btree (id)
public.experience_feature_variants idx_experience_feature_variants_experience_feature_id CREATE INDEX idx_experience_feature_variants_experience_feature_id ON public.experience_feature_variants USING btree (experience_feature_id)
public.experience_feature_variants ix_experience_feature_variants_id CREATE UNIQUE INDEX ix_experience_feature_variants_id ON public.experience_feature_variants USING btree (id)
public.experience_feature_variants ix_experience_feature_variants_pid CREATE UNIQUE INDEX ix_experience_feature_variants_pid ON public.experience_feature_variants USING btree (pid)
public.experience_features experience_features_pkey CREATE UNIQUE INDEX experience_features_pkey ON public.experience_features USING btree (id)
public.experience_features idx_experience_features_experience_id CREATE INDEX idx_experience_features_experience_id ON public.experience_features USING btree (experience_id)
public.experience_features idx_experience_features_feature_flag_id CREATE INDEX idx_experience_features_feature_flag_id ON public.experience_features USING btree (feature_id)
public.experience_features ix_experience_features_id CREATE UNIQUE INDEX ix_experience_features_id ON public.experience_features USING btree (id)
public.experience_features ix_experience_features_pid CREATE UNIQUE INDEX ix_experience_features_pid ON public.experience_features USING btree (pid)
public.experience_features uq_experience_features_exp_feat CREATE UNIQUE INDEX uq_experience_features_exp_feat ON public.experience_features USING btree (experience_id, feature_id)
public.experience_metrics experience_metrics_pkey CREATE UNIQUE INDEX experience_metrics_pkey ON public.experience_metrics USING btree (id)
public.experience_metrics ix_experience_metrics_experience_id CREATE INDEX ix_experience_metrics_experience_id ON public.experience_metrics USING btree (experience_id)
public.experience_metrics ix_experience_metrics_id CREATE UNIQUE INDEX ix_experience_metrics_id ON public.experience_metrics USING btree (id)
public.experience_metrics ix_experience_metrics_metric_id CREATE INDEX ix_experience_metrics_metric_id ON public.experience_metrics USING btree (metric_id)
public.experience_metrics ix_experience_metrics_pid CREATE UNIQUE INDEX ix_experience_metrics_pid ON public.experience_metrics USING btree (pid)
public.experience_metrics uq_experience_metrics_exp_metric CREATE UNIQUE INDEX uq_experience_metrics_exp_metric ON public.experience_metrics USING btree (experience_id, metric_id)
public.experience_variants experience_variants_pkey CREATE UNIQUE INDEX experience_variants_pkey ON public.experience_variants USING btree (id)
public.experience_variants idx_experience_variants_experience_id CREATE INDEX idx_experience_variants_experience_id ON public.experience_variants USING btree (experience_id)
public.experience_variants ix_experience_variants_id CREATE UNIQUE INDEX ix_experience_variants_id ON public.experience_variants USING btree (id)
public.experience_variants ix_experience_variants_pid CREATE UNIQUE INDEX ix_experience_variants_pid ON public.experience_variants USING btree (pid)
public.experience_variants uq_experience_variants_name_exp CREATE UNIQUE INDEX uq_experience_variants_name_exp ON public.experience_variants USING btree (name, experience_id)
public.experiences experiences_pkey CREATE UNIQUE INDEX experiences_pkey ON public.experiences USING btree (id)
public.experiences idx_experiences_name_org_app CREATE INDEX idx_experiences_name_org_app ON public.experiences USING btree (name, organisation_id, app_id)
public.experiences idx_experiences_org_app CREATE INDEX idx_experiences_org_app ON public.experiences USING btree (organisation_id, app_id)
public.experiences idx_experiences_status_org_app CREATE INDEX idx_experiences_status_org_app ON public.experiences USING btree (status, organisation_id, app_id)
public.experiences ix_experiences_id CREATE UNIQUE INDEX ix_experiences_id ON public.experiences USING btree (id)
public.experiences ix_experiences_pid CREATE UNIQUE INDEX ix_experiences_pid ON public.experiences USING btree (pid)
public.experiences uq_experiences_name_org_app CREATE UNIQUE INDEX uq_experiences_name_org_app ON public.experiences USING btree (name, organisation_id, app_id)
public.feature_flags feature_flags_pkey CREATE UNIQUE INDEX feature_flags_pkey ON public.feature_flags USING btree (id)
public.feature_flags idx_feature_flags_active_org_app CREATE INDEX idx_feature_flags_active_org_app ON public.feature_flags USING btree (is_active, organisation_id, app_id)
public.feature_flags idx_feature_flags_org_app CREATE INDEX idx_feature_flags_org_app ON public.feature_flags USING btree (organisation_id, app_id)
public.feature_flags ix_feature_flags_id CREATE UNIQUE INDEX ix_feature_flags_id ON public.feature_flags USING btree (id)
public.feature_flags ix_feature_flags_pid CREATE UNIQUE INDEX ix_feature_flags_pid ON public.feature_flags USING btree (pid)
public.feature_flags uq_feature_flags_name_org_app CREATE UNIQUE INDEX uq_feature_flags_name_org_app ON public.feature_flags USING btree (name, organisation_id, app_id)
public.invitations invitations_pkey CREATE UNIQUE INDEX invitations_pkey ON public.invitations USING btree (id)
public.invitations invitations_token_key CREATE UNIQUE INDEX invitations_token_key ON public.invitations USING btree (token)
public.invitations ix_invitations_email_org_status CREATE INDEX ix_invitations_email_org_status ON public.invitations USING btree (email, organisation_id, status)
public.invitations ix_invitations_expires_status CREATE INDEX ix_invitations_expires_status ON public.invitations USING btree (expires_at, status)
public.invitations ix_invitations_id CREATE UNIQUE INDEX ix_invitations_id ON public.invitations USING btree (id)
public.invitations ix_invitations_org_status_created CREATE INDEX ix_invitations_org_status_created ON public.invitations USING btree (organisation_id, status, created_at)
public.invitations ix_invitations_pid CREATE UNIQUE INDEX ix_invitations_pid ON public.invitations USING btree (pid)
public.metrics idx_metrics_name_org_app CREATE INDEX idx_metrics_name_org_app ON public.metrics USING btree (name, organisation_id, app_id)
public.metrics idx_metrics_org_app CREATE INDEX idx_metrics_org_app ON public.metrics USING btree (organisation_id, app_id)
public.metrics ix_metrics_id CREATE UNIQUE INDEX ix_metrics_id ON public.metrics USING btree (id)
public.metrics ix_metrics_pid CREATE UNIQUE INDEX ix_metrics_pid ON public.metrics USING btree (pid)
public.metrics metrics_pkey CREATE UNIQUE INDEX metrics_pkey ON public.metrics USING btree (id)
public.organisations ix_organisations_id CREATE UNIQUE INDEX ix_organisations_id ON public.organisations USING btree (id)
public.organisations ix_organisations_pid CREATE UNIQUE INDEX ix_organisations_pid ON public.organisations USING btree (pid)
public.organisations organisations_pkey CREATE UNIQUE INDEX organisations_pkey ON public.organisations USING btree (id)
public.personalisation_experience_variants ix_personalisation_experience_variants_experience_variant_id CREATE INDEX ix_personalisation_experience_variants_experience_variant_id ON public.personalisation_experience_variants USING btree (experience_variant_id)
public.personalisation_experience_variants ix_personalisation_experience_variants_id CREATE UNIQUE INDEX ix_personalisation_experience_variants_id ON public.personalisation_experience_variants USING btree (id)
public.personalisation_experience_variants ix_personalisation_experience_variants_personalisation_id CREATE INDEX ix_personalisation_experience_variants_personalisation_id ON public.personalisation_experience_variants USING btree (personalisation_id)
public.personalisation_experience_variants ix_personalisation_experience_variants_pid CREATE UNIQUE INDEX ix_personalisation_experience_variants_pid ON public.personalisation_experience_variants USING btree (pid)
public.personalisation_experience_variants personalisation_experience_variants_pkey CREATE UNIQUE INDEX personalisation_experience_variants_pkey ON public.personalisation_experience_variants USING btree (id)
public.personalisation_experience_variants uq_personalisation_experience_variants_per_exp_var CREATE UNIQUE INDEX uq_personalisation_experience_variants_per_exp_var ON public.personalisation_experience_variants USING btree (personalisation_id, experience_variant_id)
public.personalisation_metrics ix_personalisation_metrics_id CREATE UNIQUE INDEX ix_personalisation_metrics_id ON public.personalisation_metrics USING btree (id)
public.personalisation_metrics ix_personalisation_metrics_metric_id CREATE INDEX ix_personalisation_metrics_metric_id ON public.personalisation_metrics USING btree (metric_id)
public.personalisation_metrics ix_personalisation_metrics_personalisation_id CREATE INDEX ix_personalisation_metrics_personalisation_id ON public.personalisation_metrics USING btree (personalisation_id)
public.personalisation_metrics ix_personalisation_metrics_pid CREATE UNIQUE INDEX ix_personalisation_metrics_pid ON public.personalisation_metrics USING btree (pid)
public.personalisation_metrics personalisation_metrics_pkey CREATE UNIQUE INDEX personalisation_metrics_pkey ON public.personalisation_metrics USING btree (id)
public.personalisation_metrics uq_personalisation_metrics_pers_metric CREATE UNIQUE INDEX uq_personalisation_metrics_pers_metric ON public.personalisation_metrics USING btree (personalisation_id, metric_id)
public.personalisation_segment_rules ix_personalisation_segment_rules_id CREATE UNIQUE INDEX ix_personalisation_segment_rules_id ON public.personalisation_segment_rules USING btree (id)
public.personalisation_segment_rules ix_personalisation_segment_rules_personalisation_id CREATE INDEX ix_personalisation_segment_rules_personalisation_id ON public.personalisation_segment_rules USING btree (personalisation_id)
public.personalisation_segment_rules ix_personalisation_segment_rules_pid CREATE UNIQUE INDEX ix_personalisation_segment_rules_pid ON public.personalisation_segment_rules USING btree (pid)
public.personalisation_segment_rules ix_personalisation_segment_rules_segment_id CREATE INDEX ix_personalisation_segment_rules_segment_id ON public.personalisation_segment_rules USING btree (segment_id)
public.personalisation_segment_rules personalisation_segment_rules_pkey CREATE UNIQUE INDEX personalisation_segment_rules_pkey ON public.personalisation_segment_rules USING btree (id)
public.personalisation_segment_rules uq_personalisation_segment_rules_tr_seg CREATE UNIQUE INDEX uq_personalisation_segment_rules_tr_seg ON public.personalisation_segment_rules USING btree (personalisation_id, segment_id)
public.personalisations idx_personalisations_experience_id CREATE INDEX idx_personalisations_experience_id ON public.personalisations USING btree (experience_id)
public.personalisations idx_personalisations_priority CREATE INDEX idx_personalisations_priority ON public.personalisations USING btree (priority)
public.personalisations ix_personalisations_id CREATE UNIQUE INDEX ix_personalisations_id ON public.personalisations USING btree (id)
public.personalisations ix_personalisations_pid CREATE UNIQUE INDEX ix_personalisations_pid ON public.personalisations USING btree (pid)
public.personalisations personalisations_pkey CREATE UNIQUE INDEX personalisations_pkey ON public.personalisations USING btree (id)
public.personalisations uq_personalisations_exp_prio CREATE UNIQUE INDEX uq_personalisations_exp_prio ON public.personalisations USING btree (experience_id, priority)
public.personalisations uq_personalisations_name_exp CREATE UNIQUE INDEX uq_personalisations_name_exp ON public.personalisations USING btree (name, experience_id)
public.recommendations ix_recommendations_id CREATE UNIQUE INDEX ix_recommendations_id ON public.recommendations USING btree (id)
public.recommendations ix_recommendations_pid CREATE UNIQUE INDEX ix_recommendations_pid ON public.recommendations USING btree (pid)
public.recommendations recommendations_pkey CREATE UNIQUE INDEX recommendations_pkey ON public.recommendations USING btree (id)
public.segments idx_segments_org_app CREATE INDEX idx_segments_org_app ON public.segments USING btree (organisation_id, app_id)
public.segments ix_segments_id CREATE UNIQUE INDEX ix_segments_id ON public.segments USING btree (id)
public.segments ix_segments_pid CREATE UNIQUE INDEX ix_segments_pid ON public.segments USING btree (pid)
public.segments segments_pkey CREATE UNIQUE INDEX segments_pkey ON public.segments USING btree (id)
public.segments uq_segments_name_org_app CREATE UNIQUE INDEX uq_segments_name_org_app ON public.segments USING btree (name, organisation_id, app_id)
public.user_experience idx_user_experience_assigned_org_app CREATE INDEX idx_user_experience_assigned_org_app ON public.user_experience USING btree (assigned_at, organisation_id, app_id)
public.user_experience idx_user_experience_experience_org_app CREATE INDEX idx_user_experience_experience_org_app ON public.user_experience USING btree (experience_id, organisation_id, app_id)
public.user_experience idx_user_experience_main_query CREATE INDEX idx_user_experience_main_query ON public.user_experience USING btree (user_id, organisation_id, app_id, experience_id)
public.user_experience idx_user_experience_user_assigned CREATE INDEX idx_user_experience_user_assigned ON public.user_experience USING btree (user_id, assigned_at)
public.user_experience ix_user_experience_id CREATE UNIQUE INDEX ix_user_experience_id ON public.user_experience USING btree (id)
public.user_experience ix_user_experience_pid CREATE UNIQUE INDEX ix_user_experience_pid ON public.user_experience USING btree (pid)
public.user_experience user_experience_pkey CREATE UNIQUE INDEX user_experience_pkey ON public.user_experience USING btree (id)
public.user_profile_keys idx_user_profile_keys_org_app CREATE INDEX idx_user_profile_keys_org_app ON public.user_profile_keys USING btree (organisation_id, app_id)
public.user_profile_keys ix_user_profile_keys_id CREATE UNIQUE INDEX ix_user_profile_keys_id ON public.user_profile_keys USING btree (id)
public.user_profile_keys ix_user_profile_keys_pid CREATE UNIQUE INDEX ix_user_profile_keys_pid ON public.user_profile_keys USING btree (pid)
public.user_profile_keys uq_user_profile_keys_key_org_app CREATE UNIQUE INDEX uq_user_profile_keys_key_org_app ON public.user_profile_keys USING btree (key, organisation_id, app_id)
public.user_profile_keys user_profile_keys_pkey CREATE UNIQUE INDEX user_profile_keys_pkey ON public.user_profile_keys USING btree (id)
public.users idx_users_org_app CREATE INDEX idx_users_org_app ON public.users USING btree (organisation_id, app_id)
public.users idx_users_user_id_org_app CREATE INDEX idx_users_user_id_org_app ON public.users USING btree (user_id, organisation_id, app_id)
public.users ix_users_id CREATE UNIQUE INDEX ix_users_id ON public.users USING btree (id)
public.users ix_users_pid CREATE UNIQUE INDEX ix_users_pid ON public.users USING btree (pid)
public.users uq_users_user_id_org_app CREATE UNIQUE INDEX uq_users_user_id_org_app ON public.users USING btree (user_id, organisation_id, app_id)
public.users users_pkey CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)

-- CONSTRAINTS
public.alembic_version 2200_18394_1_not_null CHECK
public.alembic_version alembic_version_pkc PRIMARY KEY
public.apps uq_org_app_name UNIQUE
public.apps apps_organisation_id_fkey FOREIGN KEY
public.apps apps_pkey PRIMARY KEY
public.apps 2200_18824_1_not_null CHECK
public.apps 2200_18824_2_not_null CHECK
public.apps 2200_18824_5_not_null CHECK
public.apps 2200_18824_3_not_null CHECK
public.apps 2200_18824_6_not_null CHECK
public.apps 2200_18824_4_not_null CHECK
public.auth_users 2200_18842_6_not_null CHECK
public.auth_users 2200_18842_2_not_null CHECK
public.auth_users 2200_18842_1_not_null CHECK
public.auth_users 2200_18842_5_not_null CHECK
public.auth_users 2200_18842_4_not_null CHECK
public.auth_users 2200_18842_3_not_null CHECK
public.auth_users auth_users_organisation_id_fkey FOREIGN KEY
public.auth_users auth_users_pkey PRIMARY KEY
public.auth_users 2200_18842_9_not_null CHECK
public.auth_users 2200_18842_8_not_null CHECK
public.auth_users 2200_18842_7_not_null CHECK
public.events_schema 2200_18777_5_not_null CHECK
public.events_schema 2200_18777_4_not_null CHECK
public.events_schema 2200_18777_3_not_null CHECK
public.events_schema 2200_18777_2_not_null CHECK
public.events_schema 2200_18777_1_not_null CHECK
public.events_schema events_schema_pkey PRIMARY KEY
public.events_schema uq_events_schema_event_name_org_app UNIQUE
public.events_schema 2200_18777_8_not_null CHECK
public.events_schema 2200_18777_7_not_null CHECK
public.events_schema 2200_18777_6_not_null CHECK
public.experience_feature_variants 2200_18585_3_not_null CHECK
public.experience_feature_variants 2200_18585_4_not_null CHECK
public.experience_feature_variants experience_feature_variants_pkey PRIMARY KEY
public.experience_feature_variants experience_feature_variants_experience_feature_id_fkey FOREIGN KEY
public.experience_feature_variants experience_feature_variants_experience_variant_id_fkey FOREIGN KEY
public.experience_feature_variants 2200_18585_1_not_null CHECK
public.experience_feature_variants 2200_18585_2_not_null CHECK
public.experience_feature_variants 2200_18585_8_not_null CHECK
public.experience_feature_variants 2200_18585_7_not_null CHECK
public.experience_feature_variants 2200_18585_6_not_null CHECK
public.experience_feature_variants 2200_18585_5_not_null CHECK
public.experience_features 2200_18487_5_not_null CHECK
public.experience_features 2200_18487_3_not_null CHECK
public.experience_features 2200_18487_2_not_null CHECK
public.experience_features 2200_18487_1_not_null CHECK
public.experience_features experience_features_pkey PRIMARY KEY
public.experience_features uq_experience_features_exp_feat UNIQUE
public.experience_features experience_features_experience_id_fkey FOREIGN KEY
public.experience_features experience_features_feature_id_fkey FOREIGN KEY
public.experience_features 2200_18487_6_not_null CHECK
public.experience_features 2200_18487_4_not_null CHECK
public.experience_metrics experience_metrics_metric_id_fkey FOREIGN KEY
public.experience_metrics experience_metrics_experience_id_fkey FOREIGN KEY
public.experience_metrics 2200_18512_4_not_null CHECK
public.experience_metrics 2200_18512_3_not_null CHECK
public.experience_metrics 2200_18512_2_not_null CHECK
public.experience_metrics 2200_18512_1_not_null CHECK
public.experience_metrics uq_experience_metrics_exp_metric UNIQUE
public.experience_metrics experience_metrics_pkey PRIMARY KEY
public.experience_metrics 2200_18512_5_not_null CHECK
public.experience_metrics 2200_18512_6_not_null CHECK
public.experience_variants 2200_18537_2_not_null CHECK
public.experience_variants experience_variants_pkey PRIMARY KEY
public.experience_variants uq_experience_variants_name_exp UNIQUE
public.experience_variants experience_variants_experience_id_fkey FOREIGN KEY
public.experience_variants 2200_18537_1_not_null CHECK
public.experience_variants 2200_18537_3_not_null CHECK
public.experience_variants 2200_18537_4_not_null CHECK
public.experience_variants 2200_18537_5_not_null CHECK
public.experience_variants 2200_18537_6_not_null CHECK
public.experience_variants 2200_18537_7_not_null CHECK
public.experience_variants 2200_18537_8_not_null CHECK
public.experience_variants 2200_18537_9_not_null CHECK
public.experiences 2200_18400_7_not_null CHECK
public.experiences 2200_18400_8_not_null CHECK
public.experiences experiences_pkey PRIMARY KEY
public.experiences uq_experiences_name_org_app UNIQUE
public.experiences 2200_18400_2_not_null CHECK
public.experiences 2200_18400_5_not_null CHECK
public.experiences 2200_18400_6_not_null CHECK
public.experiences 2200_18400_3_not_null CHECK
public.experiences 2200_18400_9_not_null CHECK
public.experiences 2200_18400_1_not_null CHECK
public.experiences 2200_18400_4_not_null CHECK
public.feature_flags 2200_18418_11_not_null CHECK
public.feature_flags uq_feature_flags_name_org_app UNIQUE
public.feature_flags feature_flags_pkey PRIMARY KEY
public.feature_flags 2200_18418_1_not_null CHECK
public.feature_flags 2200_18418_2_not_null CHECK
public.feature_flags 2200_18418_3_not_null CHECK
public.feature_flags 2200_18418_4_not_null CHECK
public.feature_flags 2200_18418_5_not_null CHECK
public.feature_flags 2200_18418_6_not_null CHECK
public.feature_flags 2200_18418_7_not_null CHECK
public.feature_flags 2200_18418_8_not_null CHECK
public.feature_flags 2200_18418_9_not_null CHECK
public.feature_flags 2200_18418_10_not_null CHECK
public.invitations 2200_18878_2_not_null CHECK
public.invitations invitations_invited_by_fkey FOREIGN KEY
public.invitations invitations_token_key UNIQUE
public.invitations invitations_pkey PRIMARY KEY
public.invitations 2200_18878_10_not_null CHECK
public.invitations 2200_18878_11_not_null CHECK
public.invitations 2200_18878_1_not_null CHECK
public.invitations invitations_organisation_id_fkey FOREIGN KEY
public.invitations 2200_18878_3_not_null CHECK
public.invitations 2200_18878_4_not_null CHECK
public.invitations 2200_18878_5_not_null CHECK
public.invitations 2200_18878_6_not_null CHECK
public.invitations 2200_18878_7_not_null CHECK
public.invitations 2200_18878_8_not_null CHECK
public.invitations 2200_18878_9_not_null CHECK
public.metrics 2200_18436_5_not_null CHECK
public.metrics 2200_18436_1_not_null CHECK
public.metrics 2200_18436_2_not_null CHECK
public.metrics 2200_18436_3_not_null CHECK
public.metrics 2200_18436_4_not_null CHECK
public.metrics 2200_18436_6_not_null CHECK
public.metrics 2200_18436_7_not_null CHECK
public.metrics 2200_18436_8_not_null CHECK
public.metrics 2200_18436_9_not_null CHECK
public.metrics 2200_18436_10_not_null CHECK
public.metrics metrics_pkey PRIMARY KEY
public.organisations 2200_18811_1_not_null CHECK
public.organisations organisations_pkey PRIMARY KEY
public.organisations 2200_18811_5_not_null CHECK
public.organisations 2200_18811_4_not_null CHECK
public.organisations 2200_18811_3_not_null CHECK
public.organisations 2200_18811_2_not_null CHECK
public.personalisation_experience_variants personalisation_experience_variants_pkey PRIMARY KEY
public.personalisation_experience_variants personalisation_experience_variants_personalisation_id_fkey FOREIGN KEY
public.personalisation_experience_variants 2200_18610_1_not_null CHECK
public.personalisation_experience_variants 2200_18610_2_not_null CHECK
public.personalisation_experience_variants 2200_18610_3_not_null CHECK
public.personalisation_experience_variants 2200_18610_4_not_null CHECK
public.personalisation_experience_variants 2200_18610_5_not_null CHECK
public.personalisation_experience_variants 2200_18610_6_not_null CHECK
public.personalisation_experience_variants 2200_18610_7_not_null CHECK
public.personalisation_experience_variants personalisation_experience_variants_experience_variant_id_fkey FOREIGN KEY
public.personalisation_experience_variants uq_personalisation_experience_variants_per_exp_var UNIQUE
public.personalisation_metrics 2200_18635_2_not_null CHECK
public.personalisation_metrics 2200_18635_3_not_null CHECK
public.personalisation_metrics 2200_18635_4_not_null CHECK
public.personalisation_metrics 2200_18635_5_not_null CHECK
public.personalisation_metrics 2200_18635_6_not_null CHECK
public.personalisation_metrics personalisation_metrics_pkey PRIMARY KEY
public.personalisation_metrics uq_personalisation_metrics_pers_metric UNIQUE
public.personalisation_metrics personalisation_metrics_metric_id_fkey FOREIGN KEY
public.personalisation_metrics personalisation_metrics_personalisation_id_fkey FOREIGN KEY
public.personalisation_metrics 2200_18635_1_not_null CHECK
public.personalisation_segment_rules uq_personalisation_segment_rules_tr_seg UNIQUE
public.personalisation_segment_rules personalisation_segment_rules_pkey PRIMARY KEY
public.personalisation_segment_rules 2200_18660_1_not_null CHECK
public.personalisation_segment_rules 2200_18660_2_not_null CHECK
public.personalisation_segment_rules 2200_18660_3_not_null CHECK
public.personalisation_segment_rules 2200_18660_4_not_null CHECK
public.personalisation_segment_rules 2200_18660_5_not_null CHECK
public.personalisation_segment_rules 2200_18660_6_not_null CHECK
public.personalisation_segment_rules personalisation_segment_rules_segment_id_fkey FOREIGN KEY
public.personalisation_segment_rules personalisation_segment_rules_personalisation_id_fkey FOREIGN KEY
public.personalisation_segment_rules 2200_18660_7_not_null CHECK
public.personalisations personalisations_pkey PRIMARY KEY
public.personalisations 2200_18559_1_not_null CHECK
public.personalisations 2200_18559_2_not_null CHECK
public.personalisations 2200_18559_3_not_null CHECK
public.personalisations 2200_18559_4_not_null CHECK
public.personalisations 2200_18559_5_not_null CHECK
public.personalisations 2200_18559_6_not_null CHECK
public.personalisations 2200_18559_7_not_null CHECK
public.personalisations 2200_18559_8_not_null CHECK
public.personalisations 2200_18559_9_not_null CHECK
public.personalisations 2200_18559_10_not_null CHECK
public.personalisations 2200_18559_11_not_null CHECK
public.personalisations 2200_18559_12_not_null CHECK
public.personalisations 2200_18559_13_not_null CHECK
public.personalisations 2200_18559_14_not_null CHECK
public.personalisations 2200_18559_16_not_null CHECK
public.personalisations personalisations_experience_id_fkey FOREIGN KEY
public.personalisations uq_personalisations_name_exp UNIQUE
public.personalisations uq_personalisations_exp_prio UNIQUE
public.recommendations 2200_18759_4_not_null CHECK
public.recommendations 2200_18759_3_not_null CHECK
public.recommendations 2200_18759_2_not_null CHECK
public.recommendations 2200_18759_5_not_null CHECK
public.recommendations 2200_18759_1_not_null CHECK
public.recommendations 2200_18759_6_not_null CHECK
public.recommendations 2200_18759_7_not_null CHECK
public.recommendations 2200_18759_8_not_null CHECK
public.recommendations recommendations_pkey PRIMARY KEY
public.recommendations recommendations_experience_id_fkey FOREIGN KEY
public.segments uq_segments_name_org_app UNIQUE
public.segments segments_pkey PRIMARY KEY
public.segments 2200_18452_1_not_null CHECK
public.segments 2200_18452_2_not_null CHECK
public.segments 2200_18452_3_not_null CHECK
public.segments 2200_18452_4_not_null CHECK
public.segments 2200_18452_5_not_null CHECK
public.segments 2200_18452_6_not_null CHECK
public.segments 2200_18452_7_not_null CHECK
public.segments 2200_18452_8_not_null CHECK
public.segments 2200_18452_9_not_null CHECK
public.user_experience 2200_18723_11_not_null CHECK
public.user_experience 2200_18723_1_not_null CHECK
public.user_experience 2200_18723_2_not_null CHECK
public.user_experience 2200_18723_5_not_null CHECK
public.user_experience 2200_18723_6_not_null CHECK
public.user_experience 2200_18723_7_not_null CHECK
public.user_experience 2200_18723_8_not_null CHECK
public.user_experience 2200_18723_9_not_null CHECK
public.user_experience 2200_18723_10_not_null CHECK
public.user_experience 2200_18723_12_not_null CHECK
public.user_experience 2200_18723_13_not_null CHECK
public.user_experience user_experience_pkey PRIMARY KEY
public.user_experience user_experience_experience_id_fkey FOREIGN KEY
public.user_experience user_experience_personalisation_id_fkey FOREIGN KEY
public.user_experience user_experience_user_id_fkey FOREIGN KEY
public.user_profile_keys uq_user_profile_keys_key_org_app UNIQUE
public.user_profile_keys 2200_18794_9_not_null CHECK
public.user_profile_keys 2200_18794_8_not_null CHECK
public.user_profile_keys 2200_18794_7_not_null CHECK
public.user_profile_keys 2200_18794_3_not_null CHECK
public.user_profile_keys 2200_18794_2_not_null CHECK
public.user_profile_keys 2200_18794_1_not_null CHECK
public.user_profile_keys 2200_18794_6_not_null CHECK
public.user_profile_keys 2200_18794_5_not_null CHECK
public.user_profile_keys 2200_18794_4_not_null CHECK
public.user_profile_keys user_profile_keys_pkey PRIMARY KEY
public.users 2200_18469_3_not_null CHECK
public.users 2200_18469_4_not_null CHECK
public.users 2200_18469_5_not_null CHECK
public.users 2200_18469_6_not_null CHECK
public.users 2200_18469_7_not_null CHECK
public.users users_pkey PRIMARY KEY
public.users uq_users_user_id_org_app UNIQUE
public.users 2200_18469_8_not_null CHECK
public.users 2200_18469_1_not_null CHECK
public.users 2200_18469_2_not_null CHECK
