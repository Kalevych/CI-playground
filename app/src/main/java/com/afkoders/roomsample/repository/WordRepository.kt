package com.afkoders.roomsample.repository

/**
 * Created by Kalevych Oleksandr on 18.10.2020.
 */


class WordRepository(private val wordDao: WordDao){


    val allWords = wordDao.getAlphabetizedWords()

    suspend fun insert(word: Word){
        wordDao.insert(word)
    }
}