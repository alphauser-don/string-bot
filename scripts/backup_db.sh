#!/bin/bash

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backup_${TIMESTAMP}.sql"

pg_dump $DB_URI > /backups/$BACKUP_FILE

# Encrypt backup
openssl enc -aes-256-cbc -salt -in /backups/$BACKUP_FILE -out /backups/$BACKUP_FILE.enc -pass pass:$ENCRYPTION_KEY

# Delete unencrypted backup
rm /backups/$BACKUP_FILE

echo "Backup created: $BACKUP_FILE.enc"
