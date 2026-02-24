# ClickHouse tracking for UserExperience is handled directly in
# UserExperienceAsyncCRUD.bulk_create_user_experience_personalisations
# which passes external_user_id for analytics consistency.
#
# The previous after_insert listener was removed to avoid duplicate
# ClickHouse writes and to allow passing external_user_id.
