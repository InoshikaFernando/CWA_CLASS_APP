-- ==========================================
-- Migration: accounts 0003_add_block_fields
-- ==========================================
ALTER TABLE `accounts_customuser` ADD COLUMN `block_type` varchar(20) DEFAULT '' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `block_type` DROP DEFAULT;
ALTER TABLE `accounts_customuser` ADD COLUMN `is_blocked` bool DEFAULT b'0' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `is_blocked` DROP DEFAULT;

-- ==========================================
-- Migration: accounts 0004_add_must_change_password
-- ==========================================
ALTER TABLE `accounts_customuser` ADD COLUMN `must_change_password` bool DEFAULT b'0' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `must_change_password` DROP DEFAULT;

-- ==========================================
-- Migration: accounts 0005_add_user_address_fields
-- ==========================================
ALTER TABLE `accounts_customuser` ADD COLUMN `city` varchar(100) DEFAULT '' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `city` DROP DEFAULT;
ALTER TABLE `accounts_customuser` ADD COLUMN `phone` varchar(30) DEFAULT '' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `phone` DROP DEFAULT;
ALTER TABLE `accounts_customuser` ADD COLUMN `postal_code` varchar(20) DEFAULT '' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `postal_code` DROP DEFAULT;
ALTER TABLE `accounts_customuser` ADD COLUMN `street_address` varchar(255) DEFAULT '' NOT NULL;
ALTER TABLE `accounts_customuser` ALTER COLUMN `street_address` DROP DEFAULT;

-- ==========================================
-- Migration: classroom 0059_classstudent_is_active
-- ==========================================
ALTER TABLE `classroom_classstudent` ADD COLUMN `is_active` bool DEFAULT b'1' NOT NULL;
ALTER TABLE `classroom_classstudent` ALTER COLUMN `is_active` DROP DEFAULT;

-- ==========================================
-- Migration: classroom 0060_guardian_models
-- ==========================================
CREATE TABLE `classroom_guardian` (
  `id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `first_name` varchar(150) NOT NULL,
  `last_name` varchar(150) NOT NULL,
  `email` varchar(254) NOT NULL,
  `phone` varchar(30) NOT NULL,
  `relationship` varchar(20) NOT NULL,
  `address` varchar(300) NOT NULL,
  `city` varchar(100) NOT NULL,
  `country` varchar(100) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `school_id` bigint NOT NULL
);
CREATE TABLE `classroom_studentguardian` (
  `id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `is_primary` bool NOT NULL,
  `guardian_id` bigint NOT NULL,
  `student_id` bigint NOT NULL
);
ALTER TABLE `classroom_guardian` ADD CONSTRAINT `classroom_guardian_school_id_email_36b2c2fe_uniq` UNIQUE (`school_id`, `email`);
ALTER TABLE `classroom_guardian` ADD CONSTRAINT `classroom_guardian_school_id_457ea6b9_fk_classroom_school_id` FOREIGN KEY (`school_id`) REFERENCES `classroom_school` (`id`);
ALTER TABLE `classroom_studentguardian` ADD CONSTRAINT `classroom_studentguardian_student_id_guardian_id_4f41b7dd_uniq` UNIQUE (`student_id`, `guardian_id`);
ALTER TABLE `classroom_studentguardian` ADD CONSTRAINT `classroom_studentgua_guardian_id_904dded7_fk_classroom` FOREIGN KEY (`guardian_id`) REFERENCES `classroom_guardian` (`id`);
ALTER TABLE `classroom_studentguardian` ADD CONSTRAINT `classroom_studentgua_student_id_49b20527_fk_accounts_` FOREIGN KEY (`student_id`) REFERENCES `accounts_customuser` (`id`);

-- ==========================================
-- Migration: maths 0009_question_classroom_question_department
-- ==========================================
ALTER TABLE `maths_question` ADD COLUMN `classroom_id` bigint NULL;
ALTER TABLE `maths_question` ADD CONSTRAINT `maths_question_classroom_id_df3be034_fk_classroom_classroom_id` FOREIGN KEY (`classroom_id`) REFERENCES `classroom_classroom`(`id`);
ALTER TABLE `maths_question` ADD COLUMN `department_id` bigint NULL;
ALTER TABLE `maths_question` ADD CONSTRAINT `maths_question_department_id_efb91e1b_fk_classroom_department_id` FOREIGN KEY (`department_id`) REFERENCES `classroom_department`(`id`);

-- ==========================================
-- SAFE VERSION: Use IF NOT EXISTS to skip columns that already exist
-- Run these if you get "Duplicate column" errors
-- ==========================================
-- To check if a column exists before adding:
-- SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='accounts_customuser' AND COLUMN_NAME='block_type';
